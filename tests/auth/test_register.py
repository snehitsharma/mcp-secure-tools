"""register_customer: unknown callers prove a phone by SMS -> signed in or signed up."""
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from auth import build_auth
from sessions import build_sessions
from auth.approval_web import create_app
from auth.mcp_server.server import build_server
from customers import CompositeDirectory, CustomerRegistry
from shared.config import Settings
from shared.contracts.auth import Level
from shared.db import Database
from shared.fakes import FakeClock, FakeSms, InMemoryCustomers
from tests.conftest import ASHA, McpClient

NEW = "+919811111111"


@pytest.fixture
def renv() -> Iterator[tuple]:
    db, clock, sms = Database(), FakeClock(), FakeSms()
    directory = CompositeDirectory(InMemoryCustomers([ASHA]), CustomerRegistry(db, clock))
    auth = build_auth(Settings(secret_key="x" * 48, base_url="http://test", db_path=":memory:"),
                      directory, sms, clock, db=db)
    sessions = build_sessions(auth)
    with TestClient(build_server(auth).streamable_http_app(), base_url="http://localhost:8101") as http:
        yield auth, sms, McpClient(http), TestClient(create_app(auth)), directory, sessions


def _call(renv, sid, args=None):
    auth, _, mcp, _, _, sessions = renv
    r = mcp.call("register_customer", args or {}, token=sessions.token(sid))
    return r["structuredContent"]


def _link(sms):
    _, _, approval_id, secret = sms.outbox[-1].params["link"].removeprefix("http://test").split("/")
    return approval_id, secret


def test_new_caller_signs_up_with_name_typed_on_page(renv):
    auth, sms, _, web, directory, sessions = renv
    sessions.start("s1", NEW)
    r = _call(renv, "s1")
    assert r["status"] == "pending" and r["data"]["kind"] == "register"
    assert sms.outbox[-1].to == NEW and sms.outbox[-1].template == "registration_link"

    approval_id, secret = _link(sms)
    page = web.get(f"/a/{approval_id}/{secret}")
    assert "Your name" in page.text
    missing = web.post(f"/a/{approval_id}", data={"s": secret, "decision": "approve", "name": " "})
    assert missing.status_code == 422  # name required, link still usable
    ok = web.post(f"/a/{approval_id}", data={"s": secret, "decision": "approve", "name": "Priya‮ K"})
    assert ok.status_code == 200 and "signed up" in ok.text

    claims = sessions.current("s1")
    assert claims.level is Level.VERIFIED and claims.sub.startswith("cr_")
    customer = directory.get(claims.sub)
    assert customer.phone == NEW and customer.name == "Priya K"


def test_known_number_signs_in_instead(renv):
    auth, sms, _, web, directory, sessions = renv
    sessions.start("chat1", None)  # chat: no caller ID
    r = _call(renv, "chat1", {"phone": "98000 00001"})  # Asha, typed without +91
    assert r["data"]["kind"] == "signin" and sms.outbox[-1].to == ASHA.phone
    approval_id, secret = _link(sms)
    web.post(f"/a/{approval_id}", data={"s": secret, "decision": "approve"})
    assert sessions.current("chat1").sub == ASHA.id


def test_no_caller_id_needs_a_phone(renv):
    auth, *_, sessions = renv
    sessions.start("chat2", None)
    assert _call(renv, "chat2")["code"] == "phone_required"
    assert _call(renv, "chat2", {"phone": "12"})["code"] == "invalid_phone"


def test_already_identified(renv):
    auth, *_, sessions = renv
    sessions.start("s1", ASHA.phone)
    assert _call(renv, "s1")["code"] == "already_identified"


def test_reject_creates_nobody(renv):
    auth, sms, _, web, directory, sessions = renv
    sessions.start("s1", NEW)
    _call(renv, "s1")
    approval_id, secret = _link(sms)
    web.post(f"/a/{approval_id}", data={"s": secret, "decision": "reject"})
    assert directory.by_phone(NEW) is None and sessions.current("s1").sub is None


def test_same_number_twice_is_one_customer(renv):
    auth, sms, _, web, directory, sessions = renv
    for sid in ("a", "b"):
        sessions.start(sid, NEW)
        _call(renv, sid)
        approval_id, secret = _link(sms)
        web.post(f"/a/{approval_id}", data={"s": secret, "decision": "approve", "name": "P"})
    assert sessions.current("a").sub == sessions.current("b").sub


def test_one_number_cant_be_sms_bombed_across_sessions(renv):
    auth, sms, *_, sessions = renv
    for i in range(8):
        sessions.start(f"x{i}", None)
        _call(renv, f"x{i}", {"phone": NEW})
    assert sum(m.to == NEW for m in sms.outbox) == 5  # per-number daily cap


def test_unknown_caller_is_pointed_at_register(renv):
    auth, _, mcp, *_, sessions = renv
    sessions.start("s1", NEW)
    r = mcp.call("request_verification", token=sessions.token("s1"))["structuredContent"]
    assert r["code"] == "identification_required" and r["next_tool"] == "register_customer"
