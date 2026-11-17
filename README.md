# mcp-secure-tools

[![CI](https://github.com/snehitsharma/mcp-secure-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/snehitsharma/mcp-secure-tools/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[![M8ven Score](https://m8ven.ai/badge/mcp/snehitsharma/mcp-secure-tools)](https://m8ven.ai/mcp/snehitsharma/mcp-secure-tools?s=readme)

A growing library of [MCP](https://modelcontextprotocol.io) tools for voice and chat AI agents,
built on one rule: **identity never passes through the model.**

Most agents let the model collect an OTP or a customer id and pass it to the next tool. Then a
clever prompt can talk the model past the check. Here, the model only picks *which* tool to call
and *what* to ask for. *Who* is asking travels separately, as a signed token the host attaches
to every request. The model never sees it, so it can't leak or forge it.

## Tools

| Tool | Status | What it does |
|---|---|---|
| [**verification**](src/mcp_secure_tools/tools/verification) | ✅ v0.1 | Raises a caller to "verified" by an SMS approval link tapped on their own phone |
| payments | 🔜 planned | Payment links that only a verified caller can create |
| orders | 🔜 planned | Order status, history and cancellation, scoped to the caller |

Every tool shares the same **core**: tokens, levels and the gate.

## See it in 10 seconds

```sh
pip install -e ".[dev]"
python examples/end_to_end.py
```

```
1. Call starts. Host gives auth the caller ID; the model is not involved.
   token issued: level 1 for customer c_asha
2. Model tries to pay.
   model sees: {"status": "denied", "code": "verification_required", "next_tool": "request_verification"}
3. Model calls request_verification (no arguments).
   model sees: pending - An approval link was sent by SMS to the customer's registered number...
4. Customer opens the link and taps Approve.
   session is now level 2
5. Next turn: host attaches the new token, model retries.
   model sees: ok - Payment link sent for ORD-42.
```

## How it works

### Levels

| Level | Meaning | How a session gets it |
|---|---|---|
| 0 anonymous | unknown caller | call starts, number not found |
| 1 identified | caller ID matches a customer (spoofable: no sensitive actions) | call starts, number found |
| 2 verified | proved they hold the registered phone | tapped the SMS approval link (lasts 10 min) |

### What a tool call looks like

The model writes the body. The host adds the header. The tool trusts only the header.

```http
POST /mcp
Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzaWQiOiJjYWxsLTEyMyIsInN1YiI6ImNfYXNoYSIsImxldmVsIjoxfQ.CjGAKu5i...

{"jsonrpc": "2.0", "id": 7, "method": "tools/call",
 "params": {"name": "request_verification", "arguments": {}}}
```

The token is a JWT, `header.payload.signature`, one string. Its payload:

```json
{ "sid": "call-123", "sub": "c_asha", "level": 1,
  "scopes": ["customer:register", "verification:request"],
  "iat": 1794481143, "exp": 1794484743, "session_exp": 1794484743, "jti": "..." }
```

Anyone can decode it; nobody can change it without the secret key. Each token also has a DB row,
so it can be revoked early, and a session has at most one live token.

### Protecting your own tool: one line

```python
from mcp_secure_tools.core.gate import ContractViolation, Gate
from mcp_secure_tools.core.tokens import build_verifier

gate = Gate(build_verifier(settings, db))

@mcp.tool(name="create_payment")
def create_payment(order_ref: str, ctx: Context):
    try:
        claims = gate.require(ctx, min_level=Level.VERIFIED, scopes={"payment:create"})
    except ContractViolation as v:
        return v.response()   # tells the model: call request_verification, then retry
    ...                       # claims.sub is the verified customer id
```

## The verification tool

| MCP tool | Needs | Does |
|---|---|---|
| `request_verification` | level 1 | texts a one-time approval link to the customer's **registered** number |
| `register_customer` | level 0 | unknown caller: link to their number; a known number signs in, a new one signs up |

- The link's secret is 192 bits; only its SHA-256 hash is stored.
- Single use, expires in 5 minutes; a newer link cancels the older one.
- Opening the link (GET) changes nothing, so SMS previews and link scanners can't approve. Only the button (POST) does.
- Unknown link and wrong secret give the same error, so ids can't be probed.
- Rate limits per session and per phone per day, so it can't be used to SMS-bomb anyone.
- Approval page sends `no-store`, `no-referrer`, `X-Frame-Options: DENY` and a strict CSP.
- SMS through msg91 (India DLT: path-only links, exact templates), Twilio, or the console.

Run it (MCP at `/mcp`, approval page at `/a/...`, one port):

```sh
export TL_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
python -m mcp_secure_tools.tools.verification      # :8100
```

Per-business settings (customer DB, SMS provider, message text) go in `tenant.toml`; see
[`tenant.example.toml`](tenant.example.toml). Without one you get a demo customer
(+919800000001) and SMS printed to the console.

## Layout

```
src/mcp_secure_tools/
  core/                  shared by every tool
    tokens.py            issue / verify / revoke signed tokens
    gate.py              the check every tool runs first: token → level → scopes
    policy.py            which level grants which scopes
    sessions.py          host side: start a session from caller ID, current token each turn
    customers/           read customers from the business DB (+ registry for sign-ups)
    contracts/           Pydantic models shared across tools
  providers/sms/         msg91, twilio, console
  tools/
    verification/        request_verification, register_customer, approval page
examples/                end_to_end.py
tests/                   core/ and tools/<name>/
```

## Roadmap

- HTTP endpoint for hosts to start a session (today the host runs `core.sessions` in-process)
- Capture spoken numbers on the host side so the model never passes them
- payments and orders tools

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The one rule: never trust identity that came from a tool
argument.

## License

[MIT](LICENSE)
