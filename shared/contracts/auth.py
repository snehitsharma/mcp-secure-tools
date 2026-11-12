from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class Level(IntEnum):
    ANONYMOUS = 0   # unknown caller
    IDENTIFIED = 1  # caller ID matches a registered customer
    VERIFIED = 2    # customer approved a link sent to the registered number


class Role(StrEnum):
    CUSTOMER = "customer"


class Claims(BaseModel):
    """What a signed token asserts. Lives server-side; the model never sees it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    jti: str
    sid: str                 # session the token is bound to
    sub: str | None = None   # customer id, None at level 0
    role: Role
    level: Level
    scopes: frozenset[str]
    iat: int
    exp: int
    session_exp: int         # hard session expiry; no token outlives it

    def has(self, *scopes: str) -> bool:
        return set(scopes) <= self.scopes


class AuthError(Exception):
    """code is stable and machine-readable; never includes secrets."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class TokenExpired(AuthError):
    def __init__(self, claims: Claims) -> None:
        super().__init__("expired")
        self.claims = claims


class TokenVerifier(Protocol):
    """What every tool server needs from auth: check a token, get claims.
    Raises AuthError / TokenExpired."""

    def verify(self, token: str) -> Claims: ...
