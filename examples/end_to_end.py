"""The whole flow in one script, no network: python examples/end_to_end.py

A known customer calls in, tries to pay, is asked to verify, taps the SMS link,
and the payment goes through. Watch what the model sees at each step.
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from mcp.server.fastmcp import Context, FastMCP

from mcp_secure_tools.core.config import Settings
from mcp_secure_tools.core.contracts.auth import Level
from mcp_secure_tools.core.contracts.customers import Customer
from mcp_secure_tools.core.contracts.tools import ToolResult, ToolStatus
from mcp_secure_tools.core.db import Database
from mcp_secure_tools.core.fakes import FakeSms, InMemoryCustomers
from mcp_secure_tools.core.gate import ContractViolation, Gate, respond
from mcp_secure_tools.tools.verification import build_sessions, build_verification
from mcp_secure_tools.tools.verification.approval_web import create_app
from mcp_secure_tools.tools.verification.server import register

ASHA = Customer(id="c_asha", name="Asha", phone="+919800000001")


def your_payment_tool(mcp: FastMCP, gate: Gate) -> None:
    """Any tool of yours: one gate line protects it."""

    @mcp.tool(name="create_payment")
    def create_payment(order_ref: str, ctx: Context):
        try:
            claims = gate.require(ctx, min_level=Level.VERIFIED, scopes={"payment:create"})
        except ContractViolation as v:
            return v.response()
        return respond(ToolResult(status=ToolStatus.OK, message=f"Payment link sent for {order_ref}.",
                                  data={"customer": claims.sub}))


def call(http: TestClient, token: str, tool: str, args: dict | None = None) -> dict:
    """What the host does on every tool call: the model picks tool + args, the host adds the token."""
    r = http.post("/mcp", headers={"Authorization": f"Bearer {token}",
                                   "Accept": "application/json, text/event-stream"},
                  json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": tool, "arguments": args or {}}})
    return r.json()["result"]["structuredContent"]


def main() -> None:
    sms = FakeSms()
    settings = Settings(secret_key="demo-" + "x" * 40, base_url="http://localhost:8100", db_path=":memory:")
    verification = build_verification(settings, InMemoryCustomers([ASHA]), sms, db=Database())
    sessions = build_sessions(verification)

    mcp = FastMCP("demo", stateless_http=True, json_response=True, log_level="WARNING")
    gate = Gate(verification.tokens)
    register(mcp, verification, gate)
    your_payment_tool(mcp, gate)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    with TestClient(mcp.streamable_http_app(), base_url="http://localhost:8100") as http:
        web = TestClient(create_app(verification))

        print("1. Call starts. Host gives auth the caller ID; the model is not involved.")
        claims = sessions.start("call-123", caller_id=ASHA.phone)
        print(f"   token issued: level {int(claims.level)} for customer {claims.sub}\n")

        print("2. Model tries to pay.")
        r = call(http, sessions.token("call-123"), "create_payment", {"order_ref": "ORD-42"})
        print("   model sees:", json.dumps({k: r[k] for k in ("status", "code", "next_tool")}), "\n")

        print("3. Model calls request_verification (no arguments).")
        r = call(http, sessions.token("call-123"), "request_verification")
        print("   model sees:", r["status"], "-", r["message"])
        print("   SMS sent:  ", sms.outbox[-1].body, "\n")

        print("4. Customer opens the link and taps Approve.")
        _, _, approval_id, secret = urlparse(re.search(r"https?://\S+", sms.outbox[-1].body)[0]).path.split("/")
        web.post(f"/a/{approval_id}", data={"s": secret, "decision": "approve"})
        print(f"   session is now level {int(sessions.current('call-123').level)}\n")

        print("5. Next turn: host attaches the new token, model retries.")
        r = call(http, sessions.token("call-123"), "create_payment", {"order_ref": "ORD-42"})
        print("   model sees:", r["status"], "-", r["message"])
        print("\nThe model never saw a token, a phone number or a secret.")


if __name__ == "__main__":
    main()
