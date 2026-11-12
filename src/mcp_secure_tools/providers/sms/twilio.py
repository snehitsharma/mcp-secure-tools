"""Twilio Messages API. Sends the rendered body as-is. For India, the body must
still match a DLT template registered through Twilio."""
from __future__ import annotations

import os
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, model_validator

from mcp_secure_tools.core.contracts.messaging import OutboundSms


class TwilioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["twilio"] = "twilio"
    account_sid: str
    auth_token_env: str = "TL_TWILIO_AUTH_TOKEN"
    from_number: str | None = None
    messaging_service_sid: str | None = None
    timeout_s: float = 10.0

    @model_validator(mode="after")
    def _sender(self) -> TwilioConfig:
        if not (self.from_number or self.messaging_service_sid):
            raise ValueError("set from_number or messaging_service_sid")
        return self


class TwilioSms:
    def __init__(self, cfg: TwilioConfig, client: httpx.Client | None = None) -> None:
        token = os.environ.get(cfg.auth_token_env)
        if not token:
            raise RuntimeError(f"Twilio auth token missing: set {cfg.auth_token_env}")
        self._cfg = cfg
        self._auth = (cfg.account_sid, token)
        self._url = f"https://api.twilio.com/2010-04-01/Accounts/{cfg.account_sid}/Messages.json"
        self._client = client or httpx.Client(timeout=cfg.timeout_s)

    def send_sms(self, msg: OutboundSms) -> str:
        form = {"To": msg.to, "Body": msg.body}
        if self._cfg.messaging_service_sid:
            form["MessagingServiceSid"] = self._cfg.messaging_service_sid
        else:
            form["From"] = self._cfg.from_number
        r = self._client.post(self._url, data=form, auth=self._auth)
        r.raise_for_status()
        return r.json()["sid"]
