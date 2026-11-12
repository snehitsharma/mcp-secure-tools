"""The tool-call contract shared by every MCP server.

When a call breaks the contract (no token, expired token, level too low), the
server answers with isError=true and a ToolResult whose `code` says why and,
where possible, `next_tool` says what the model should call to fix it."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolArgs(BaseModel):
    """Base for tool arguments. Unknown fields are rejected, so the model
    can't slip in customer_id / level / phone."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolStatus(StrEnum):
    OK = "ok"
    PENDING = "pending"
    DENIED = "denied"
    INVALID = "invalid"
    ERROR = "error"


class ContractCode(StrEnum):
    AUTH_REQUIRED = "auth_required"                    # no/invalid/revoked token: host problem
    TOKEN_EXPIRED = "token_expired"                    # host refreshes token and retries
    IDENTIFICATION_REQUIRED = "identification_required"  # level 0, no known customer
    VERIFICATION_REQUIRED = "verification_required"    # call next_tool, then retry
    FORBIDDEN = "forbidden"                            # level ok but scope missing


class ToolResult(BaseModel):
    status: ToolStatus
    message: str
    code: str | None = None
    required_level: int | None = None
    next_tool: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        return self.status in (ToolStatus.DENIED, ToolStatus.INVALID, ToolStatus.ERROR)
