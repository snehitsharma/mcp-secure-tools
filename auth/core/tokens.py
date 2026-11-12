"""Signed tokens (JWT HS256) backed by a DB row per token for revocation.
Owns table: auth_tokens."""
from __future__ import annotations

import secrets
from collections.abc import Callable

import jwt
from pydantic import ValidationError

from shared.contracts.auth import AuthError, TokenExpired
from auth.core.policy import scopes_for
from shared.contracts.auth import Claims, Level, Role
from shared.db import Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_tokens (
    jti         TEXT PRIMARY KEY,
    sid         TEXT NOT NULL,
    sub         TEXT,
    level       INTEGER NOT NULL,
    token       TEXT NOT NULL,
    issued_at   INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL,
    revoked_at  INTEGER
);
CREATE INDEX IF NOT EXISTS ix_auth_tokens_sid ON auth_tokens (sid, revoked_at);
"""

_REQUIRED = ["jti", "sid", "role", "level", "scopes", "iat", "exp", "session_exp"]


class TokenService:
    ALGORITHM = "HS256"

    def __init__(self, db: Database, secret: str, clock: Callable[[], int]) -> None:
        if len(secret.encode()) < 32:
            raise ValueError("secret_key must be at least 32 bytes")
        self._db = db
        self._secret = secret
        self._clock = clock
        db.migrate(SCHEMA)

    def issue(
        self, sid: str, sub: str | None, level: Level, *, ttl_s: int, session_exp: int
    ) -> Claims:
        """Issue a token and revoke every other live token for the session,
        so a session has at most one live token."""
        now = self._clock()
        claims = Claims(
            jti=secrets.token_urlsafe(16),
            sid=sid,
            sub=sub,
            role=Role.CUSTOMER,
            level=level,
            scopes=scopes_for(level),
            iat=now,
            exp=min(now + ttl_s, session_exp),
            session_exp=session_exp,
        )
        # PyJWT requires sub to be a string when present, so leave it out at level 0.
        payload = claims.model_dump(mode="json", exclude_none=True)
        payload["scopes"] = sorted(claims.scopes)
        token = jwt.encode(payload, self._secret, algorithm=self.ALGORITHM)
        with self._db.transaction():
            self._db.execute(
                "UPDATE auth_tokens SET revoked_at = ? WHERE sid = ? AND revoked_at IS NULL",
                (now, sid),
            )
            self._db.execute(
                "INSERT INTO auth_tokens (jti, sid, sub, level, token, issued_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (claims.jti, sid, sub, int(level), token, now, claims.exp),
            )
        return claims

    def active_token(self, sid: str) -> str | None:
        row = self._db.one(
            "SELECT token FROM auth_tokens WHERE sid = ? AND revoked_at IS NULL"
            " ORDER BY issued_at DESC LIMIT 1",
            (sid,),
        )
        return row["token"] if row else None

    def verify(self, token: str) -> Claims:
        """Signature, then revocation, then expiry. TokenExpired carries the
        (authentic) claims so the caller can decide on a fallback."""
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self.ALGORITHM],
                # expiry is checked against our own clock below
                options={"verify_exp": False, "verify_iat": False, "require": _REQUIRED},
            )
            claims = Claims.model_validate(payload)
        except (jwt.PyJWTError, ValidationError) as e:
            raise AuthError("invalid_token") from e

        row = self._db.one("SELECT revoked_at FROM auth_tokens WHERE jti = ?", (claims.jti,))
        if row is None or row["revoked_at"] is not None:
            raise AuthError("revoked")
        if self._clock() >= claims.exp:
            raise TokenExpired(claims)
        return claims

    def revoke_session(self, sid: str) -> None:
        self._db.execute(
            "UPDATE auth_tokens SET revoked_at = ? WHERE sid = ? AND revoked_at IS NULL",
            (self._clock(), sid),
        )
