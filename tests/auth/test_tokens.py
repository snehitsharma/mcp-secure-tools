import jwt
import pytest

from shared.contracts.auth import AuthError, TokenExpired
from shared.contracts.auth import Level
from tests.conftest import ASHA


def test_caller_id_match_gives_level_1(env):
    claims = env.sessions.start("s1", "+91 98000-00001")
    assert claims.level is Level.IDENTIFIED
    assert claims.sub == ASHA.id
    assert claims.has("verification:request")
    assert not claims.has("payment:create")


@pytest.mark.parametrize("caller_id", [None, "", "+919999999999", "not-a-number"])
def test_unknown_or_missing_caller_id_gives_level_0(env, caller_id):
    claims = env.sessions.start("s1", caller_id)
    assert claims.level is Level.ANONYMOUS
    assert claims.sub is None
    assert not claims.has("verification:request")


def test_session_cannot_be_started_twice(env):
    env.sessions.start("s1", ASHA.phone)
    with pytest.raises(AuthError, match="session_exists"):
        env.sessions.start("s1", ASHA.phone)


def test_reissue_revokes_previous_token(env):
    env.sessions.start("s1", ASHA.phone)
    old = env.auth.tokens.active_token("s1")
    env.auth.tokens.issue("s1", ASHA.id, Level.IDENTIFIED, ttl_s=60, session_exp=env.clock() + 60)
    with pytest.raises(AuthError, match="revoked"):
        env.auth.tokens.verify(old)


def test_tampered_token_rejected(env):
    env.sessions.start("s1", ASHA.phone)
    token = env.auth.tokens.active_token("s1")
    payload = jwt.decode(token, options={"verify_signature": False})
    payload["level"] = 2
    forged = jwt.encode(payload, "y" * 48, algorithm="HS256")
    with pytest.raises(AuthError, match="invalid_token"):
        env.auth.tokens.verify(forged)


def test_alg_none_rejected(env):
    env.sessions.start("s1", ASHA.phone)
    payload = jwt.decode(env.auth.tokens.active_token("s1"), options={"verify_signature": False})
    unsigned = jwt.encode(payload, None, algorithm="none")
    with pytest.raises(AuthError, match="invalid_token"):
        env.auth.tokens.verify(unsigned)


def test_session_expiry_ends_session(env):
    env.sessions.start("s1", ASHA.phone)
    env.clock.advance(env.settings.session_ttl_s)
    with pytest.raises(AuthError, match="session_expired"):
        env.sessions.current("s1")
    assert env.auth.tokens.active_token("s1") is None


def test_expired_raises_token_expired_with_claims(env):
    env.sessions.start("s1", ASHA.phone)
    token = env.auth.tokens.active_token("s1")
    env.clock.advance(env.settings.session_ttl_s)
    with pytest.raises(TokenExpired) as e:
        env.auth.tokens.verify(token)
    assert e.value.claims.sub == ASHA.id


def test_short_secret_refused():
    from auth.core.tokens import TokenService
    from shared.db import Database

    with pytest.raises(ValueError):
        TokenService(Database(), "short", lambda: 0)
