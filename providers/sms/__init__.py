"""SMS providers behind contracts.messaging.SmsSender. Pick one in tenant.toml."""
from __future__ import annotations

import itertools
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts.messaging import OutboundSms, SmsSender
from providers.sms.msg91 import Msg91Config, Msg91Sms
from providers.sms.twilio import TwilioConfig, TwilioSms


class ConsoleConfig(BaseModel):
    """Dev only: prints the SMS (with its link) to the server log."""

    model_config = ConfigDict(extra="forbid")
    provider: Literal["console"] = "console"


class ConsoleSms:
    def __init__(self) -> None:
        self._ids = itertools.count(1)

    def send_sms(self, msg: OutboundSms) -> str:
        print(f"[sms -> {msg.to}] {msg.body}", flush=True)
        return f"console-{next(self._ids)}"


SmsConfig = Annotated[
    ConsoleConfig | Msg91Config | TwilioConfig, Field(discriminator="provider")
]


def build_sms(cfg: ConsoleConfig | Msg91Config | TwilioConfig) -> SmsSender:
    if isinstance(cfg, Msg91Config):
        return Msg91Sms(cfg)
    if isinstance(cfg, TwilioConfig):
        return TwilioSms(cfg)
    return ConsoleSms()


__all__ = ["SmsConfig", "build_sms"]
