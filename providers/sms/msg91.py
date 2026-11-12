"""MSG91 Flow API (India, DLT). The message text lives in MSG91 as a DLT-approved
template; we send its id plus variable values.

Verify against your account before going live: MSG91's docs disagree on a few
details (template_id vs flow_id, authkey in header vs body). Their dashboard's
"Try" option shows the exact request.
"""
from __future__ import annotations

import os
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from shared.contracts.messaging import OutboundSms

FLOW_URL = "https://control.msg91.com/api/v5/flow"


class Msg91Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["msg91"] = "msg91"
    authkey_env: str = "TL_MSG91_AUTHKEY"
    # logical template name -> MSG91 template (flow) id
    templates: dict[str, str]
    # our param name -> the variable name in the MSG91 template (case-sensitive)
    variables: dict[str, str] = Field(default_factory=lambda: {"link": "link", "minutes": "minutes"})
    timeout_s: float = 10.0


class Msg91Sms:
    def __init__(self, cfg: Msg91Config, client: httpx.Client | None = None) -> None:
        key = os.environ.get(cfg.authkey_env)
        if not key:
            raise RuntimeError(f"MSG91 auth key missing: set {cfg.authkey_env}")
        self._cfg = cfg
        self._key = key
        self._client = client or httpx.Client(timeout=cfg.timeout_s)

    def send_sms(self, msg: OutboundSms) -> str:
        template_id = self._cfg.templates.get(msg.template)
        if template_id is None:
            raise ValueError(f"no MSG91 template configured for {msg.template!r}")
        recipient = {"mobiles": msg.to.lstrip("+")}
        for ours, value in msg.params.items():
            # renamed if mapped, otherwise passed under our own name
            recipient[self._cfg.variables.get(ours, ours)] = value
        r = self._client.post(
            FLOW_URL,
            headers={"authkey": self._key, "accept": "application/json"},
            # short_url off: a shortener would see the one-time secret and swap
            # in a domain that isn't the one you whitelisted.
            json={"template_id": template_id, "short_url": "0", "recipients": [recipient]},
        )
        r.raise_for_status()
        body = r.json()
        if body.get("type") != "success":
            raise RuntimeError(f"MSG91 rejected the message: {body.get('message')}")
        return str(body.get("message", ""))
