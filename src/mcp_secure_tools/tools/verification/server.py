"""Verification MCP server: request_verification, register_customer.

The model calls it when the customer asks to verify, or after another tool
fails with code=verification_required / next_tool=request_verification.

No arguments: who to verify comes from the token (sub, sid); where to send
the link comes from the customer directory. Stateless HTTP; no MCP sessions.
"""
from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult

from mcp_secure_tools.core.contracts.auth import AuthError, Level
from mcp_secure_tools.core.contracts.tools import ToolResult, ToolStatus
from mcp_secure_tools.core.gate import REGISTER_TOOL, VERIFY_TOOL, ContractViolation, Gate, respond
from mcp_secure_tools.core.playbook import instructions
from mcp_secure_tools.tools.verification.service import VerificationService

_REGISTER_FAILURES = {
    "phone_required": (ToolStatus.INVALID, "No caller ID on this call: ask for their mobile number and pass it as phone."),
    "invalid_phone": (ToolStatus.INVALID, "That doesn't look like a valid mobile number. Ask again."),
    "rate_limited": (ToolStatus.DENIED, "Too many sign-up attempts. Try again later."),
    "send_failed": (ToolStatus.ERROR, "Could not send the SMS. Try again shortly."),
    "registration_unavailable": (ToolStatus.DENIED, "Sign-up isn't available for this business."),
}

_FAILURES = {
    "rate_limited": (ToolStatus.DENIED, "Too many verification attempts on this call."),
    "send_failed": (ToolStatus.ERROR, "Could not send the approval SMS. Try again shortly."),
    "unknown_customer": (ToolStatus.DENIED, "No registered customer on this call."),
}


def register(mcp: FastMCP, auth: VerificationService, gate: Gate) -> None:

    @mcp.tool(
        name=VERIFY_TOOL,
        description=(
            "Send the customer an approval link by SMS to their registered phone number. "
            "Call this when the customer asks to verify, or when another tool fails with "
            "code 'verification_required'. After they tap Approve, retry the original action."
        ),
    )
    def request_verification(ctx: Context) -> CallToolResult:
        try:
            claims = gate.require(ctx, min_level=Level.IDENTIFIED, scopes={"verification:request"})
        except ContractViolation as v:
            return v.response()

        if claims.level >= Level.VERIFIED:
            return respond(ToolResult(status=ToolStatus.OK, message="The customer is already verified."))
        try:
            auth.request_verification(claims.sid, claims.sub)
        except AuthError as e:
            status, message = _FAILURES.get(e.code, (ToolStatus.ERROR, "Verification failed."))
            return respond(ToolResult(status=status, code=e.code, message=message))

        minutes = max(1, auth.approval_ttl_s // 60)
        return respond(
            ToolResult(
                status=ToolStatus.PENDING,
                message=(
                    "An approval link was sent by SMS to the customer's registered number. "
                    f"Ask them to open it and tap Approve within {minutes} minutes, then retry "
                    "the action that needed verification."
                ),
                data={"expires_in_s": auth.approval_ttl_s},
            )
        )

    @mcp.tool(
        name=REGISTER_TOOL,
        description=(
            "For a caller who isn't a known customer (tools say identification_required). Sends "
            "a link by SMS to their number: a known number signs them in, a new one signs them "
            "up (they type their name on the page). Uses the number they're calling from; pass "
            "`phone` only if they want a different number or there's no caller ID (chat). "
            "After they approve, retry what they wanted."
        ),
    )
    def register_customer(ctx: Context, phone: str | None = None) -> CallToolResult:
        try:
            claims = gate.require(ctx, min_level=Level.ANONYMOUS, scopes={"customer:register"})
        except ContractViolation as v:
            return v.response()
        if claims.sub is not None:
            return respond(ToolResult(status=ToolStatus.OK, code="already_identified",
                                      message="This caller is already a known customer."))
        try:
            approval = auth.register_or_signin(claims.sid, phone)
        except AuthError as e:
            status, message = _REGISTER_FAILURES.get(
                e.code, (ToolStatus.ERROR, "Couldn't start sign-up."))
            return respond(ToolResult(status=status, code=e.code, message=message))
        minutes = max(1, auth.approval_ttl_s // 60)
        what = "sign up" if approval.kind == "register" else "sign in"
        return respond(ToolResult(
            status=ToolStatus.PENDING,
            message=(f"A link was sent by SMS to the number ending {approval.phone[-2:]}. Ask them "
                     f"to open it and {what} within {minutes} minutes, then retry what they wanted."),
            data={"kind": approval.kind.value, "expires_in_s": auth.approval_ttl_s},
        ))



def build_server(auth: VerificationService, gate: Gate | None = None) -> FastMCP:
    mcp = FastMCP("verification", instructions=instructions("verification"),
                  stateless_http=True, json_response=True)
    register(mcp, auth, gate or Gate(auth.tokens))
    return mcp
