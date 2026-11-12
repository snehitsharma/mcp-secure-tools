"""The contract check every MCP tool server runs before doing anything.

Stateless: everything it needs is in the request (the bearer token the host
attached). It never takes identity from tool arguments and never stores anything.

    claims = gate.require(ctx, min_level=Level.VERIFIED, scopes={"payment:create"})

On failure it raises ContractViolation; the tool returns `violation.response()`.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from mcp.types import CallToolResult, TextContent

from mcp_secure_tools.core.contracts.auth import AuthError, Claims, Level, TokenExpired, TokenVerifier
from mcp_secure_tools.core.contracts.tools import ContractCode, ToolResult, ToolStatus

VERIFY_TOOL = "request_verification"
REGISTER_TOOL = "register_customer"


def respond(result: ToolResult) -> CallToolResult:
    """ToolResult -> MCP result. Contract failures come back with isError=true."""
    body = result.model_dump(mode="json", exclude_none=True)
    if not body.get("data"):
        body.pop("data", None)
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(body))],
        structuredContent=body,
        isError=result.is_error,
    )


class ContractViolation(Exception):
    def __init__(self, result: ToolResult) -> None:
        super().__init__(result.code or result.status)
        self.result = result

    def response(self) -> CallToolResult:
        return respond(self.result)


def _deny(code: ContractCode, message: str, **extra: Any) -> ContractViolation:
    return ContractViolation(
        ToolResult(status=ToolStatus.DENIED, code=code, message=message, **extra)
    )


def bearer_token(ctx: Any) -> str | None:
    """Token from the HTTP Authorization header the host set. The model can't
    put it there, and tool arguments are never consulted."""
    request = getattr(getattr(ctx, "request_context", None), "request", None)
    if request is None:
        return None
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


class Gate:
    def __init__(self, verifier: TokenVerifier) -> None:
        self._verifier = verifier

    def require(self, ctx: Any, *, min_level: Level, scopes: Iterable[str] = ()) -> Claims:
        return self.check(bearer_token(ctx), min_level=min_level, scopes=scopes)

    def check(self, token: str | None, *, min_level: Level, scopes: Iterable[str] = ()) -> Claims:
        if not token:
            raise _deny(ContractCode.AUTH_REQUIRED, "No session token on this request.")
        try:
            claims = self._verifier.verify(token)
        except TokenExpired:
            raise _deny(ContractCode.TOKEN_EXPIRED, "Session token expired; refresh and retry.")
        except AuthError:
            raise _deny(ContractCode.AUTH_REQUIRED, "Session token not valid.")

        if claims.level < min_level:
            if claims.sub is None:
                raise _deny(
                    ContractCode.IDENTIFICATION_REQUIRED,
                    f"This caller isn't a known customer yet. Call {REGISTER_TOOL} to sign them "
                    "in or up by SMS, then retry.",
                    required_level=int(min_level),
                    next_tool=REGISTER_TOOL,
                )
            raise _deny(
                ContractCode.VERIFICATION_REQUIRED,
                f"This action needs a verified customer. Call {VERIFY_TOOL}, ask the customer "
                "to approve the SMS link, then retry.",
                required_level=int(min_level),
                next_tool=VERIFY_TOOL,
            )
        if not claims.has(*scopes):
            raise _deny(ContractCode.FORBIDDEN, "Not permitted for this session.")
        return claims
