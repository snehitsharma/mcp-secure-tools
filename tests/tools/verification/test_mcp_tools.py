"""request_verification over real MCP JSON-RPC, as a model's host would call it."""
from mcp_secure_tools.core.contracts.auth import Level
from tests.conftest import ASHA


def _verify(env, token):
    return env.auth_mcp.call("request_verification", token=token)


def test_tool_is_listed(env):
    assert env.auth_mcp.list_tools() == ["request_verification", "register_customer"]


def test_contract_failure_then_verify_then_retry(env):
    """The main loop: a feature tool fails on contract, the model calls verification, retries."""
    env.sessions.start("s1", ASHA.phone)
    token = env.sessions.token("s1")

    # 1. model tries a level-2 tool with a level-1 session
    r = env.payments_mcp.call("create_payment", {"order_ref": "o_1"}, token=token)
    assert r["isError"] is True
    assert r["structuredContent"]["code"] == "verification_required"
    assert r["structuredContent"]["next_tool"] == "request_verification"
    assert r["structuredContent"]["required_level"] == 2

    # 2. model follows next_tool
    r = _verify(env, token)
    assert r["isError"] is False
    assert r["structuredContent"]["status"] == "pending"
    assert env.sms.outbox[-1].to == ASHA.phone

    # 3. customer approves on their phone
    assert env.approve_last_link().status_code == 200

    # 4. the old token was revoked by the upgrade; host refreshes on the next turn
    r = env.payments_mcp.call("create_payment", {"order_ref": "o_1"}, token=token)
    assert r["structuredContent"]["code"] == "auth_required"
    token = env.sessions.token("s1")
    r = env.payments_mcp.call("create_payment", {"order_ref": "o_1"}, token=token)
    assert r["isError"] is False
    assert r["structuredContent"]["data"] == {"for": ASHA.id, "order": "o_1"}


def test_no_token(env):
    r = _verify(env, None)
    assert r["isError"] is True
    assert r["structuredContent"]["code"] == "auth_required"
    assert env.sms.outbox == []


def test_garbage_token(env):
    r = _verify(env, "not.a.jwt")
    assert r["structuredContent"]["code"] == "auth_required"


def test_level_0_gets_identification_required(env):
    env.sessions.start("anon", None)
    token = env.sessions.token("anon")
    r = _verify(env, token)
    assert r["structuredContent"]["code"] == "identification_required"
    assert r["structuredContent"]["next_tool"] == "register_customer"
    r = env.payments_mcp.call("create_payment", {"order_ref": "o_1"}, token=token)
    assert r["structuredContent"]["code"] == "identification_required"
    assert env.sms.outbox == []


def test_expired_token_tells_host_to_refresh(env):
    env.sessions.start("s1", ASHA.phone)
    token = env.sessions.token("s1")
    _verify(env, token)
    env.approve_last_link()
    token = env.sessions.token("s1")
    env.clock.advance(env.settings.verified_ttl_s)
    r = env.payments_mcp.call("create_payment", {"order_ref": "o_1"}, token=token)
    assert r["structuredContent"]["code"] == "token_expired"
    # refresh drops back to level 1 → contract says verify again
    token = env.sessions.token("s1")
    assert env.sessions.current("s1").level is Level.IDENTIFIED
    r = env.payments_mcp.call("create_payment", {"order_ref": "o_1"}, token=token)
    assert r["structuredContent"]["code"] == "verification_required"


def test_already_verified(env):
    env.sessions.start("s1", ASHA.phone)
    _verify(env, env.sessions.token("s1"))
    env.approve_last_link()
    sent = len(env.sms.outbox)
    r = _verify(env, env.sessions.token("s1"))
    assert r["structuredContent"]["status"] == "ok"
    assert len(env.sms.outbox) == sent


def test_rate_limit(env):
    env.sessions.start("s1", ASHA.phone)
    token = env.sessions.token("s1")
    for _ in range(env.settings.approval_max_per_session):
        assert _verify(env, token)["structuredContent"]["status"] == "pending"
    r = _verify(env, token)
    assert r["isError"] is True and r["structuredContent"]["code"] == "rate_limited"


def test_sms_failure(env):
    env.sessions.start("s1", ASHA.phone)
    env.sms.fail = True
    r = _verify(env, env.sessions.token("s1"))
    assert r["isError"] is True and r["structuredContent"]["code"] == "send_failed"


def test_arguments_cannot_redirect_the_sms(env):
    env.sessions.start("s1", ASHA.phone)
    env.auth_mcp.call(
        "request_verification",
        {"phone": "+911234567890", "customer_id": "c_ravi"},
        token=env.sessions.token("s1"),
    )
    assert all(m.to == ASHA.phone for m in env.sms.outbox)
