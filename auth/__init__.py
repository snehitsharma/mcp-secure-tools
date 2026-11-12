"""Auth: who are you? Prove it (SMS approval link), get a signed token.
Every tool server checks that token itself with build_verifier; none of them
calls auth to do it. Owns tables auth_tokens, auth_approvals.

Session lifecycle is NOT here (see sessions/). Customer data is NOT here
either: auth reads it through a CustomerDirectory (see customers/)."""
from __future__ import annotations

import time
from collections.abc import Callable

from auth.core.service import AuthService
from auth.core.service import DEFAULT_APPROVAL_TEXT, DEFAULT_REGISTRATION_TEXT
from shared.config import Settings
from shared.contracts.auth import TokenVerifier
from shared.contracts.customers import CustomerDirectory
from shared.contracts.messaging import SmsSender
from shared.db import Database


def build_auth(
    settings: Settings,
    customers: CustomerDirectory,
    sms: SmsSender,
    clock: Callable[[], int] = lambda: int(time.time()),
    db: Database | None = None,
    approval_text: str = DEFAULT_APPROVAL_TEXT,
    registration_text: str = DEFAULT_REGISTRATION_TEXT,
) -> AuthService:
    return AuthService(
        db or Database(settings.db_path), customers, sms, settings, clock,
        approval_text=approval_text, registration_text=registration_text,
    )


def build_verifier(
    settings: Settings,
    db: Database,
    clock: Callable[[], int] = lambda: int(time.time()),
) -> TokenVerifier:
    """What every tool server needs from auth: check a token. Nothing else."""
    from auth.core.tokens import TokenService

    return TokenService(db, settings.secret_key.get_secret_value(), clock)


__all__ = ["AuthService", "build_auth", "build_verifier"]
