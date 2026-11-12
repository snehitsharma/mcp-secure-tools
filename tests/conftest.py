from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult

from mcp_secure_tools.core.config import Settings
from mcp_secure_tools.core.contracts.auth import Level
from mcp_secure_tools.core.contracts.customers import Customer
from mcp_secure_tools.core.contracts.tools import ToolResult, ToolStatus
from mcp_secure_tools.core.db import Database
from mcp_secure_tools.core.fakes import FakeClock, FakeSms, InMemoryCustomers
from mcp_secure_tools.core.gate import ContractViolation, Gate, respond
from mcp_secure_tools.core.sessions import SessionService
from mcp_secure_tools.tools.verification import VerificationService, build_sessions, build_verification
from mcp_secure_tools.tools.verification.approval_web import create_app

ASHA = Customer(id="c_asha", name="Asha", phone="+919800000001")
RAVI = Customer(id="c_ravi", name="Ravi", phone="+919800000002")


def stand_in_payments_server(gate: Gate) -> FastMCP:
    """Stand-in for a feature server built later: one tool that needs level 2."""
    mcp = FastMCP("payments-stub", stateless_http=True, json_response=True)

    @mcp.tool(name="create_payment")
    def create_payment(order_ref: str, ctx: Context) -> CallToolResult:
        try:
            claims = gate.require(ctx, min_level=Level.VERIFIED, scopes={"payment:create"})
        except ContractViolation as v:
            return v.response()
        return respond(
            ToolResult(status=ToolStatus.OK, message="link sent", data={"for": claims.sub, "order": order_ref})
        )

    return mcp


class McpClient:
    """What the host does: attach the session token as a header, call a tool."""

    def __init__(self, http: TestClient) -> None:
        self._http = http
        self._ids = 0

    def rpc(self, method: str, params: dict[str, Any], token: str | None) -> dict[str, Any]:
        self._ids += 1
        headers = {"Accept": "application/json, text/event-stream"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = self._http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": self._ids, "method": method, "params": params},
            headers=headers,
        )
        r.raise_for_status()
        body = r.json()
        assert "error" not in body, body
        return body["result"]

    def call(self, name: str, args: dict[str, Any] | None = None, *, token: str | None) -> dict[str, Any]:
        return self.rpc("tools/call", {"name": name, "arguments": args or {}}, token)

    def list_tools(self) -> list[str]:
        return [t["name"] for t in self.rpc("tools/list", {}, None)["tools"]]


@dataclass
class Env:
    verification: VerificationService
    sms: FakeSms
    clock: FakeClock
    settings: Settings
    web: TestClient
    auth_mcp: McpClient
    payments_mcp: McpClient
    sessions: SessionService = field(init=False)

    def __post_init__(self) -> None:
        self.sessions = build_sessions(self.verification)

    def link_parts(self) -> tuple[str, str]:
        _, a, approval_id, secret = urlparse(self.sms.last_link()).path.split("/")
        assert a == "a"
        return approval_id, secret

    def approve_last_link(self, decision: str = "approve"):
        approval_id, secret = self.link_parts()
        return self.web.post(f"/a/{approval_id}", data={"s": secret, "decision": decision})


@pytest.fixture
def env() -> Iterator[Env]:
    from mcp_secure_tools.tools.verification.server import build_server

    settings = Settings(secret_key="x" * 48, base_url="http://test", db_path=":memory:")
    clock = FakeClock()
    sms = FakeSms()
    verification = build_verification(settings, InMemoryCustomers([ASHA, RAVI]), sms, clock, db=Database())
    gate = Gate(verification.tokens)
    with (
        TestClient(build_server(verification, gate).streamable_http_app(), base_url="http://localhost:8101") as auth_http,
        TestClient(stand_in_payments_server(gate).streamable_http_app(), base_url="http://localhost:8101") as pay_http,
    ):
        yield Env(
            verification, sms, clock, settings,
            web=TestClient(create_app(verification)),
            auth_mcp=McpClient(auth_http),
            payments_mcp=McpClient(pay_http),
        )
