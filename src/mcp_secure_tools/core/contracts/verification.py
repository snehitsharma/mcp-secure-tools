from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"  # a newer request replaced it, or the session ended
    FAILED = "failed"          # the SMS could not be sent


class ApprovalKind(StrEnum):
    VERIFY = "verify"      # known customer on this session -> level 2
    SIGNIN = "signin"      # unbound session, known number -> bound + level 2
    REGISTER = "register"  # unbound session, new number -> customer created + bound + level 2


class Approval(BaseModel):
    """An approval request. Never carries the secret."""

    model_config = ConfigDict(frozen=True)

    id: str
    session_id: str
    kind: ApprovalKind = ApprovalKind.VERIFY
    customer_id: str | None
    phone: str
    status: ApprovalStatus
    created_at: int
    expires_at: int
    decided_at: int | None = None
