"""SessionService: the host's side. Who is on this call/chat and at what level.

Never proves anything. It starts a session from the caller ID (level 1 if the
number is a known customer, else level 0), hands the host the current token
each turn, and drops level 2 back to level 1 when it expires. Raising to level 2
is the verification tool's job.

Owns table: auth_sessions.
"""
from __future__ import annotations

from collections.abc import Callable

from mcp_secure_tools.core.config import Settings
from mcp_secure_tools.core.contracts.auth import AuthError, Claims, Level, TokenExpired
from mcp_secure_tools.core.contracts.customers import CustomerDirectory, normalize_phone
from mcp_secure_tools.core.db import Database
from mcp_secure_tools.core.tokens import TokenService

SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_sessions (
    sid         TEXT PRIMARY KEY,
    caller_id   TEXT,
    started_at  INTEGER NOT NULL
);
"""


class SessionService:
    def __init__(
        self,
        db: Database,
        customers: CustomerDirectory,
        tokens: TokenService,
        settings: Settings,
        clock: Callable[[], int],
    ) -> None:
        self._db = db
        self._customers = customers
        self._settings = settings
        self._clock = clock
        self._on_end: list[Callable[[str], None]] = []
        db.migrate(SCHEMA)
        self.tokens = tokens

    def on_end(self, listener: Callable[[str], None]) -> None:
        """Run listener(sid) when a session ends (e.g. auth cancels pending links)."""
        self._on_end.append(listener)

    def start(self, sid: str, caller_id: str | None) -> Claims:
        """Level 1 only when the caller ID matches a registered number.
        Caller ID can be spoofed, which is why level 1 grants no money actions."""
        if self.tokens.active_token(sid) is not None:
            raise AuthError("session_exists")
        phone = normalize_phone(caller_id)
        customer = self._customers.by_phone(phone) if phone else None
        level = Level.IDENTIFIED if customer else Level.ANONYMOUS
        now = self._clock()
        self._db.execute(
            "INSERT OR REPLACE INTO auth_sessions (sid, caller_id, started_at) VALUES (?, ?, ?)",
            (sid, phone, now))
        return self.tokens.issue(
            sid,
            customer.id if customer else None,
            level,
            ttl_s=self._settings.session_ttl_s,
            session_exp=now + self._settings.session_ttl_s,
        )

    def caller_id(self, sid: str) -> str | None:
        row = self._db.one("SELECT caller_id FROM auth_sessions WHERE sid = ?", (sid,))
        return row["caller_id"] if row else None

    def current(self, sid: str) -> Claims:
        """Claims for this turn. When a level 2 token expires it falls back to
        level 1 for the rest of the session; past session_exp, the session is over."""
        token = self.tokens.active_token(sid)
        if token is None:
            raise AuthError("no_session")
        try:
            return self.tokens.verify(token)
        except TokenExpired as e:
            old = e.claims
            if old.level is Level.VERIFIED and self._clock() < old.session_exp:
                return self.tokens.issue(
                    sid,
                    old.sub,
                    Level.IDENTIFIED,
                    ttl_s=old.session_exp - self._clock(),
                    session_exp=old.session_exp,
                )
            self.end(sid)
            raise AuthError("session_expired") from e

    def token(self, sid: str) -> str:
        """For the host, once per turn: the token to attach to every MCP request.
        Picks up level changes (approval, level 2 expiry) since the last turn."""
        self.current(sid)
        token = self.tokens.active_token(sid)
        if token is None:
            raise AuthError("no_session")
        return token

    def end(self, sid: str) -> None:
        self.tokens.revoke_session(sid)
        for listener in self._on_end:
            listener(sid)
