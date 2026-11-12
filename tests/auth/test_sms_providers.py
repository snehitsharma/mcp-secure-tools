"""Provider adapters build the right HTTP request. No network: httpx.MockTransport."""
import json
from pathlib import Path

import httpx
import pytest

from shared.contracts.messaging import OutboundSms
from providers.sms.msg91 import FLOW_URL, Msg91Config, Msg91Sms
from providers.sms.twilio import TwilioConfig, TwilioSms
from auth.tenant import load_tenant

MSG = OutboundSms(
    to="+919800000001",
    template="approval_link",
    params={"link": "https://shop.example/a/abc/def", "minutes": "5"},
    body="Tap to approve your request: https://shop.example/a/abc/def Expires in 5 min.",
)


def _client(handler):
    seen = []

    def wrap(request):
        seen.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrap)), seen


def test_msg91_sends_template_vars(monkeypatch):
    monkeypatch.setenv("TL_MSG91_AUTHKEY", "k123")
    client, seen = _client(lambda r: httpx.Response(200, json={"type": "success", "message": "req-1"}))
    sms = Msg91Sms(
        Msg91Config(templates={"approval_link": "tpl_9"}, variables={"link": "VAR1", "minutes": "VAR2"}),
        client,
    )
    assert sms.send_sms(MSG) == "req-1"
    req = seen[0]
    assert str(req.url) == FLOW_URL
    assert req.headers["authkey"] == "k123"
    assert json.loads(req.content) == {
        "template_id": "tpl_9",
        "short_url": "0",
        "recipients": [{"mobiles": "919800000001", "VAR1": MSG.params["link"], "VAR2": "5"}],
    }


def test_msg91_error_raises(monkeypatch):
    monkeypatch.setenv("TL_MSG91_AUTHKEY", "k")
    client, _ = _client(lambda r: httpx.Response(200, json={"type": "error", "message": "bad template"}))
    sms = Msg91Sms(Msg91Config(templates={"approval_link": "t"}), client)
    with pytest.raises(RuntimeError, match="bad template"):
        sms.send_sms(MSG)


def test_msg91_unknown_template(monkeypatch):
    monkeypatch.setenv("TL_MSG91_AUTHKEY", "k")
    sms = Msg91Sms(Msg91Config(templates={}), _client(lambda r: httpx.Response(200))[0])
    with pytest.raises(ValueError):
        sms.send_sms(MSG)


def test_twilio_sends_body(monkeypatch):
    monkeypatch.setenv("TL_TWILIO_AUTH_TOKEN", "tok")
    client, seen = _client(lambda r: httpx.Response(201, json={"sid": "SM1"}))
    sms = TwilioSms(TwilioConfig(account_sid="AC1", messaging_service_sid="MG1"), client)
    assert sms.send_sms(MSG) == "SM1"
    req = seen[0]
    assert str(req.url).endswith("/Accounts/AC1/Messages.json")
    form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
    assert form["To"] == "%2B919800000001" and form["MessagingServiceSid"] == "MG1"
    assert req.headers["authorization"].startswith("Basic ")


def test_missing_provider_secret(monkeypatch):
    monkeypatch.delenv("TL_MSG91_AUTHKEY", raising=False)
    with pytest.raises(RuntimeError, match="TL_MSG91_AUTHKEY"):
        Msg91Sms(Msg91Config(templates={"approval_link": "t"}))


def test_example_tenant_file_parses():
    cfg = load_tenant(Path(__file__).parents[2] / "tenant.example.toml")
    assert cfg.customers.backend == "sql" and cfg.customers.phone_format == "national"
    assert cfg.sms.provider == "msg91" and "approval_link" in cfg.sms.templates
    assert "{link}" in cfg.messages.approval_link


def test_approval_sms_fits_one_segment(env):
    from tests.conftest import ASHA

    env.sessions.start("s1", ASHA.phone)
    c = env.sessions.current("s1")
    env.auth.request_verification(c.sid, c.sub)
    link = env.sms.outbox[-1].params["link"]
    assert "?" not in link and link.startswith("http://test/a/")
    assert len(link) - len("http://test") < 60  # leaves room for a real domain + text
