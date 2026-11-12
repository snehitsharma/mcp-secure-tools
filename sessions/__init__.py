"""Sessions: the system's side. Starts a session for a call/chat, remembers the
caller ID, gives the host the current token each turn. It never proves anything
and never makes tokens itself: it asks auth's TokenService for them.
Sessions imports auth; auth never imports sessions."""
from __future__ import annotations

from auth import AuthService
from sessions.service import SessionService


def build_sessions(auth: AuthService) -> SessionService:
    """Sessions on the same DB, clock and customer directory as auth, wired both ways:
    auth can look up a session's caller ID; ending a session cancels its pending links."""
    sessions = SessionService(auth.db, auth.customers, auth.tokens, auth.settings, auth.clock)
    sessions.on_end(auth.cancel_pending)
    auth.caller_ids = sessions.caller_id
    return sessions


__all__ = ["SessionService", "build_sessions"]
