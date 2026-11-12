"""Verification tool: raise a session to level 2 by an SMS approval link.

    request_verification   known customer -> link to their registered number
    register_customer      unknown caller -> link to the number they claim

The customer taps Approve on their own phone; only then is a level 2 token
issued. Tokens and the gate live in core/ and are shared by every tool.
Owns table: auth_approvals.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from mcp_secure_tools.core.config import Settings
from mcp_secure_tools.core.contracts.customers import CustomerDirectory
from mcp_secure_tools.core.contracts.messaging import SmsSender
from mcp_secure_tools.core.db import Database
from mcp_secure_tools.core.sessions import SessionService
from mcp_secure_tools.core.tokens import TokenService
from mcp_secure_tools.tools.verification.service import (
    DEFAULT_APPROVAL_TEXT,
    DEFAULT_REGISTRATION_TEXT,
    VerificationService,
)


def build_verification(
    settings: Settings,
    customers: CustomerDirectory,
    sms: SmsSender,
    clock: Callable[[], int] = lambda: int(time.time()),
    db: Database | None = None,
    approval_text: str = DEFAULT_APPROVAL_TEXT,
    registration_text: str = DEFAULT_REGISTRATION_TEXT,
    tokens: TokenService | None = None,
) -> VerificationService:
    db = db or Database(settings.db_path)
    tokens = tokens or TokenService(db, settings.secret_key.get_secret_value(), clock)
    return VerificationService(
        db, customers, sms, tokens, settings, clock,
        approval_text=approval_text, registration_text=registration_text,
    )


def build_sessions(verification: VerificationService) -> SessionService:
    """Host-side sessions sharing verification's DB, clock, customers and tokens.
    Wired both ways: verification can read a session's caller ID, and ending a
    session cancels its pending links."""
    sessions = SessionService(verification.db, verification.customers, verification.tokens,
                              verification.settings, verification.clock)
    sessions.on_end(verification.cancel_pending)
    verification.caller_ids = sessions.caller_id
    return sessions


__all__ = ["VerificationService", "build_sessions", "build_verification"]
