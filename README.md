# auth-service

Caller verification for voice and chat AI agents, as an MCP tool. **Identity never passes through
the model.**

Most agents ask the model to collect an OTP and pass it along, so a clever prompt can talk the
model past the check. Here the model can only *ask* for verification. The proof happens on the
customer's own phone, and the result is a signed token the model never sees.

## How it works

```
1. Call starts        system  ── sid + caller ID ──►  auth   number found in customer DB?
                                                             yes → level 1 token, no → level 0
                                                             (stored; the model never sees it)

2. Every turn         system attaches the token:  Authorization: Bearer <token>
                      every tool checks it itself (signature, expiry, level). No call to auth.

3. Needs level 2      tool refuses: "verification_required, next_tool=request_verification"
                      model calls request_verification  (no arguments: who = inside the token)
                      auth texts a one-time link to the customer's REGISTERED number
                      tool replies "pending: ask them to tap Approve"

4. Customer taps      link opens a page → GET shows the button (changes nothing)
   Approve            POST approves → auth issues a level 2 token, revokes the old one

5. Next turn          system attaches the new token → the sensitive action goes through
                      level 2 expires after 10 min and drops back to level 1
```

| Level | Means | How you get it |
|---|---|---|
| 0 anonymous | unknown caller | session start |
| 1 identified | caller ID matches a customer (spoofable, so no sensitive actions) | session start |
| 2 verified | holds the registered phone | tapped the SMS approval link |

## The token

A JWT (HS256): `header.payload.signature`, one string. Payload:

```json
{ "sid": "call-123", "sub": "c_asha", "level": 1,
  "scopes": ["customer:register", "verification:request"],
  "iat": 1794481143, "exp": 1794484743, "session_exp": 1794484743, "jti": "..." }
```

Readable by anyone (base64), unforgeable without the secret key. Each token also has a DB row, so
it can be revoked before it expires; a session has at most one live token.

## Tools

| Tool | Needs | Does |
|---|---|---|
| `request_verification` | level 1 | texts an approval link to the customer's registered number |
| `register_customer` | level 0 | unknown caller: texts a link to their number; known number signs in, new one signs up |

## Protecting your own tool

```python
from shared.gate import Gate, ContractViolation
from auth import build_verifier

gate = Gate(build_verifier(settings, db))

@mcp.tool(name="create_payment")
def create_payment(order_ref: str, ctx: Context):
    try:
        claims = gate.require(ctx, min_level=Level.VERIFIED, scopes={"payment:create"})
    except ContractViolation as v:
        return v.response()          # tells the model to call request_verification
    ...                              # claims.sub = the verified customer id
```

## Security details

- The approval link's secret is 192 bits; only its SHA-256 hash is stored.
- An unknown link id and a wrong secret give the same error (no probing).
- Links are single use, expire in 5 minutes, and a newer link cancels the older one.
- Rate limits per session and per phone per day (no SMS bombing).
- Approval page: `no-store`, `no-referrer`, no framing, strict CSP.
- Indian DLT SMS rules supported (path-only links, exact templates); msg91, Twilio or console.

## Layout

```
auth/
  core/service.py     the flow: request link → inspect/decide link → level 2 token
  core/tokens.py      issue / verify / revoke tokens
  core/policy.py      which level grants which scopes
  mcp_server/         the two MCP tools                    :8101/mcp
  approval_web/       the page the SMS link opens          :8100/a/...
sessions/             host side: start a session from caller ID, current token each turn
customers/            read customers from the business DB (+ a registry for sign-ups)
providers/sms/        msg91, twilio, console
shared/gate.py        the check every tool runs (token → level → scopes)
```

## Run

```sh
pip install -e .[dev]
python -m pytest -q

export TL_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
python -m auth.approval_web    # :8100
python -m auth.mcp_server      # :8101/mcp  (console SMS prints the link)
```

Per-business config (customer DB, SMS provider, message text) goes in `tenant.toml`; see
`tenant.example.toml`. Without one: a demo customer (+919800000001) and SMS printed to the console.

## Roadmap

- HTTP endpoint for the host to start a session (today the host runs `sessions` in-process)
- Spoken numbers captured by the host, never passed by the model
