# Changelog

## 0.1.0 — 2026-11-12

First release.

### Core
- Signed session tokens (JWT HS256) with a DB row per token for early revocation; one live token per session.
- Levels 0 / 1 / 2 with cumulative scopes.
- Gate: the check every tool runs first (token → level → scopes), with contract errors the model can act on.
- Sessions: start from caller ID, current token per turn, level 2 drops back to level 1 on expiry.
- Customer directory adapters: in-memory, SQL (read-only), and a registry for sign-ups.
- SMS providers: msg91 (India DLT), Twilio, console.

### Tools
- **verification**: `request_verification` and `register_customer`, with an SMS approval page.
