"""AuthService: who are you? Prove it, get a token. Nothing else.

The whole flow, in the order it happens:

  1. The system starts a call -> sessions/ asks self.tokens for a level 0/1 token.
  2. A tool needs level 2 -> the model calls an auth tool:
       request_verification(sid, customer_id)  known customer: link to their registered number
       register_or_signin(sid, phone)          unknown caller: link to the number they claim
     Both end in _send_link: one-time secret, SMS, row in auth_approvals.
  3. The person opens the link (approval page):
       inspect_link   GET: shows the buttons, changes nothing
       decide_link    POST: approve/reject, single use
  4. Approved -> _grant_level_2 -> new token with level 2. The old one is revoked.

Session lifecycle (start, caller ID, per-turn token for the host) is the
system's job and lives in sessions/. Auth never imports it.
Owns tables: auth_tokens (via TokenService), auth_approvals.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import unicodedata
from collections.abc import Callable

from auth.core.tokens import TokenService
from shared.config import Settings
from shared.contracts.auth import AuthError, Claims, Level
from shared.contracts.customers import CustomerDirectory, CustomerRegistrar, normalize_phone
from shared.contracts.messaging import OutboundSms, SmsSender
from shared.contracts.verification import Approval, ApprovalKind, ApprovalStatus
from shared.db import Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_approvals (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    kind         TEXT NOT NULL,
    customer_id  TEXT,
    phone        TEXT NOT NULL,
    secret_hash  TEXT NOT NULL,
    status       TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    expires_at   INTEGER NOT NULL,
    decided_at   INTEGER
);
CREATE INDEX IF NOT EXISTS ix_auth_approvals_session ON auth_approvals (session_id, status);
CREATE INDEX IF NOT EXISTS ix_auth_approvals_phone ON auth_approvals (phone, created_at);
"""

PENDING = ApprovalStatus.PENDING.value
MAX_LINKS_PER_PHONE_PER_DAY = 5

# Placeholders: {link}, {minutes}. With DLT these must match the registered
# templates exactly, so they're set per business in tenant.toml.
DEFAULT_APPROVAL_TEXT = (
    "Tap to approve your request: {link} Expires in {minutes} min. "
    "If you did not ask for this, ignore this message."
)
DEFAULT_REGISTRATION_TEXT = (
    "Tap to confirm your number and finish signing up: {link} Expires in {minutes} min. "
    "If you did not ask for this, ignore this message."
)


class AuthService:
    def __init__(
        self,
        db: Database,
        customers: CustomerDirectory,
        sms: SmsSender,
        settings: Settings,
        clock: Callable[[], int],
        approval_text: str = DEFAULT_APPROVAL_TEXT,
        registration_text: str = DEFAULT_REGISTRATION_TEXT,
        registrar: CustomerRegistrar | None = None,
    ) -> None:
        self.db = db
        self.customers = customers
        self.settings = settings
        self.clock = clock
        self._sms = sms
        self._registrar = registrar or (customers if hasattr(customers, "register") else None)
        self._base_url = settings.base_url.rstrip("/")
        self._texts = {ApprovalKind.VERIFY: approval_text, ApprovalKind.SIGNIN: approval_text,
                       ApprovalKind.REGISTER: registration_text}
        # Where to find the number a session is calling from. The system plugs this
        # in (sessions/); without it, register_customer needs an explicit phone.
        self.caller_ids: Callable[[str], str | None] = lambda sid: None
        db.migrate(SCHEMA)
        self.tokens = TokenService(db, settings.secret_key.get_secret_value(), clock)

    @property
    def approval_ttl_s(self) -> int:
        return self.settings.approval_ttl_s

    # == 2. ask for proof (called by the auth tools) =========================

    def request_verification(
        self, sid: str, customer_id: str, kind: ApprovalKind = ApprovalKind.VERIFY
    ) -> Approval:
        """Known customer: link goes to their *registered* number, never one the caller gives."""
        customer = self.customers.get(customer_id)
        if customer is None:
            raise AuthError("unknown_customer")
        return self._send_link(sid, kind, customer.phone, customer.id)

    def register_or_signin(self, sid: str, phone: str | None) -> Approval:
        """Unknown caller: link goes to the number being claimed, so tapping it proves
        they hold that phone. Known number -> sign in; new number -> sign up (name
        typed on the page). Uses the caller ID unless a number is given."""
        claims = self._claims(sid)
        if claims.sub is not None:
            raise AuthError("already_identified")
        target = self._parse_phone(phone) if phone else self.caller_ids(sid)
        if target is None:
            raise AuthError("phone_required" if not phone else "invalid_phone")
        existing = self.customers.by_phone(target)
        if existing:
            return self.request_verification(sid, existing.id, ApprovalKind.SIGNIN)
        if self._registrar is None:
            raise AuthError("registration_unavailable")
        return self._send_link(sid, ApprovalKind.REGISTER, target, None)

    def cancel_pending(self, sid: str) -> None:
        """Session ended: its unused links stop working."""
        self._supersede_pending(sid, self.clock())

    # == 3. the person opens the link (called by the approval page) ==========

    def inspect_link(self, approval_id: str, secret: str) -> Approval:
        """GET: validates the link; never records a decision, so SMS previews
        and link scanners can't approve anything."""
        with self.db.transaction():
            self._check_secret(approval_id, secret)
            return self._expire_if_due(approval_id)

    def decide_link(
        self, approval_id: str, secret: str, *, approve: bool, name: str | None = None
    ) -> Approval:
        """POST: approve or reject. Single use. The approval and the level 2 token
        commit together or not at all. Registration needs the name typed on the page."""
        error: str | None = None
        with self.db.transaction():
            self._check_secret(approval_id, secret)
            approval = self._expire_if_due(approval_id)
            if approval.status is ApprovalStatus.EXPIRED:
                error = "expired_link"
            elif approval.status is not ApprovalStatus.PENDING:
                error = "not_pending"
            else:
                clean = _clean_name(name or "")
                if approve and approval.kind is ApprovalKind.REGISTER and not clean:
                    raise AuthError("name_required")
                status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
                self._set_status(approval_id, status, self.clock())
                approval = self._get(approval_id)
                if approve:
                    self._grant_level_2(approval, clean or None)
        if error:
            raise AuthError(error)
        return approval

    # == 4. proof succeeded -> level 2 token =================================

    def _grant_level_2(self, approval: Approval, name: str | None) -> None:
        """Runs inside decide_link's transaction; any raise rolls the approval back."""
        claims = self._claims(approval.session_id)  # session still alive? before creating anyone
        if approval.kind is ApprovalKind.REGISTER:
            if self._registrar is None:
                raise AuthError("registration_unavailable")
            customer_id = self._registrar.register(name or "Customer", approval.phone).id
        else:
            customer_id = approval.customer_id
        if claims.sub is not None and claims.sub != customer_id:
            raise AuthError("customer_mismatch")
        if claims.sub == customer_id and claims.level >= Level.VERIFIED:
            return
        self.tokens.issue(
            claims.sid,
            customer_id,
            Level.VERIFIED,
            ttl_s=self.settings.verified_ttl_s,
            session_exp=claims.session_exp,
        )

    # == internals ===========================================================

    def _send_link(self, sid: str, kind: ApprovalKind, phone: str, customer_id: str | None) -> Approval:
        now = self.clock()
        sent = self.db.one("SELECT COUNT(*) AS n FROM auth_approvals WHERE session_id = ?",
                           (sid,))["n"]
        if sent >= self.settings.approval_max_per_session:
            raise AuthError("rate_limited")
        # Per-number cap across sessions, so nobody can SMS-bomb a number.
        to_phone = self.db.one(
            "SELECT COUNT(*) AS n FROM auth_approvals WHERE phone = ? AND created_at > ?",
            (phone, now - 86400))["n"]
        if to_phone >= MAX_LINKS_PER_PHONE_PER_DAY:
            raise AuthError("rate_limited")

        approval_id = secrets.token_urlsafe(12)  # 96 bits, an identifier only
        secret = secrets.token_urlsafe(24)       # 192 bits, only its hash is stored
        with self.db.transaction():
            self._supersede_pending(sid, now)
            self.db.execute(
                "INSERT INTO auth_approvals (id, session_id, kind, customer_id, phone, secret_hash,"
                " status, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (approval_id, sid, kind.value, customer_id, phone, _hash(secret), PENDING,
                 now, now + self.approval_ttl_s),
            )
        # Path-only link (no "?"): India's DLT whitelists the static prefix {base_url}/a/.
        params = {"link": f"{self._base_url}/a/{approval_id}/{secret}",
                  "minutes": str(max(1, self.approval_ttl_s // 60))}
        template = "registration_link" if kind is ApprovalKind.REGISTER else "approval_link"
        try:
            self._sms.send_sms(OutboundSms(to=phone, template=template, params=params,
                                           body=self._texts[kind].format(**params)))
        except Exception as e:
            self._set_status(approval_id, ApprovalStatus.FAILED, now)
            raise AuthError("send_failed") from e
        return self._get(approval_id)

    def _claims(self, sid: str) -> Claims:
        """The session's live token, checked. Raises if there is none or it's dead."""
        token = self.tokens.active_token(sid)
        if token is None:
            raise AuthError("no_session")
        return self.tokens.verify(token)

    def _parse_phone(self, raw: str) -> str | None:
        digits = "".join(ch for ch in raw if ch.isdigit())
        if raw.strip().startswith("+"):
            return normalize_phone("+" + digits)
        cc = self.settings.default_country_code
        if digits.startswith("0"):
            digits = digits.lstrip("0")
        if digits.startswith(cc) and len(digits) > 10:
            return normalize_phone("+" + digits)
        return normalize_phone("+" + cc + digits)

    def _check_secret(self, approval_id: str, secret: str) -> None:
        row = self.db.one("SELECT secret_hash FROM auth_approvals WHERE id = ?", (approval_id,))
        # Same error for an unknown id and a wrong secret, so the response can't be used to probe ids.
        expected = row["secret_hash"] if row else _hash("")
        if row is None or not secret or not hmac.compare_digest(_hash(secret), expected):
            raise AuthError("invalid_link")

    def _expire_if_due(self, approval_id: str) -> Approval:
        now = self.clock()
        self.db.execute(
            "UPDATE auth_approvals SET status = ?, decided_at = ?"
            " WHERE id = ? AND status = ? AND expires_at <= ?",
            (ApprovalStatus.EXPIRED.value, now, approval_id, PENDING, now),
        )
        return self._get(approval_id)

    def _supersede_pending(self, sid: str, now: int) -> None:
        self.db.execute(
            "UPDATE auth_approvals SET status = ?, decided_at = ? WHERE session_id = ? AND status = ?",
            (ApprovalStatus.SUPERSEDED.value, now, sid, PENDING),
        )

    def _set_status(self, approval_id: str, status: ApprovalStatus, now: int) -> None:
        self.db.execute(
            "UPDATE auth_approvals SET status = ?, decided_at = ? WHERE id = ?",
            (status.value, now, approval_id),
        )

    def _get(self, approval_id: str) -> Approval:
        row = self.db.one(
            "SELECT id, session_id, kind, customer_id, phone, status, created_at, expires_at,"
            " decided_at FROM auth_approvals WHERE id = ?",
            (approval_id,),
        )
        if row is None:
            raise AuthError("invalid_link")
        return Approval.model_validate(dict(row))


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _clean_name(raw: str) -> str:
    raw = "".join(ch for ch in raw if unicodedata.category(ch)[0] != "C")
    return re.sub(r"\s+", " ", raw).strip()[:60]
