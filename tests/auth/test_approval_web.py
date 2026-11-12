"""The approval page, driven directly against auth core."""
from shared.contracts.auth import Level
from tests.conftest import ASHA


def _start_and_request(env, sid="s1"):
    env.sessions.start(sid, ASHA.phone)
    claims = env.sessions.current(sid)
    env.auth.request_verification(claims.sid, claims.sub)


def test_get_shows_buttons_and_changes_nothing(env):
    _start_and_request(env)
    approval_id, secret = env.link_parts()
    page = env.web.get(f"/a/{approval_id}/{secret}")
    assert page.status_code == 200 and "Approve" in page.text
    assert page.headers["referrer-policy"] == "no-referrer"
    assert env.sessions.current("s1").level is Level.IDENTIFIED


def test_approve_raises_level(env):
    _start_and_request(env)
    assert env.approve_last_link().status_code == 200
    assert env.sessions.current("s1").level is Level.VERIFIED


def test_single_use(env):
    _start_and_request(env)
    assert env.approve_last_link().status_code == 200
    assert env.approve_last_link().status_code == 410


def test_wrong_secret_and_unknown_id_look_the_same(env):
    _start_and_request(env)
    approval_id, _ = env.link_parts()
    a = env.web.post(f"/a/{approval_id}", data={"s": "nope", "decision": "approve"})
    b = env.web.post("/a/nope", data={"s": "nope", "decision": "approve"})
    assert a.status_code == b.status_code == 404
    assert env.sessions.current("s1").level is Level.IDENTIFIED


def test_expired(env):
    _start_and_request(env)
    env.clock.advance(env.settings.approval_ttl_s)
    assert env.approve_last_link().status_code == 410
    assert env.sessions.current("s1").level is Level.IDENTIFIED


def test_reject(env):
    _start_and_request(env)
    r = env.approve_last_link("reject")
    assert r.status_code == 200 and "Declined" in r.text
    assert env.sessions.current("s1").level is Level.IDENTIFIED


def test_newer_link_supersedes_older(env):
    _start_and_request(env)
    old_id, old_secret = env.link_parts()
    claims = env.sessions.current("s1")
    env.auth.request_verification(claims.sid, claims.sub)
    r = env.web.post(f"/a/{old_id}", data={"s": old_secret, "decision": "approve"})
    assert r.status_code == 410


def test_ended_session_link_is_dead(env):
    _start_and_request(env)
    env.sessions.end("s1")
    assert env.approve_last_link().status_code == 410
