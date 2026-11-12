from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class OutboundSms(BaseModel):
    """One message, in both shapes providers need:
    - template + params: for template-based providers (MSG91 Flow / DLT)
    - body: the rendered text, for providers that send raw text (Twilio, console)"""

    model_config = ConfigDict(frozen=True)

    to: str                     # E.164, always the registered number
    template: str               # logical name, e.g. "approval_link"
    params: dict[str, str]      # e.g. {"link": ..., "minutes": "5"}
    body: str


class SmsSender(Protocol):
    def send_sms(self, msg: OutboundSms) -> str:
        """Send and return the provider's message id. Raise on failure."""
        ...
