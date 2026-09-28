"""AuthService recognises our own services by their generated tokens (no database)."""

from services.auth_service import SERVICE_BFF, AuthService


def test_only_the_exact_configured_token_identifies_the_service():
    auth = AuthService(database=None, jwt_secret="s", token_ttl_minutes=1, service_tokens={SERVICE_BFF: "a" * 48})
    assert auth.verify_service_token("a" * 48) == SERVICE_BFF
    assert auth.verify_service_token("a" * 47) is None
    assert auth.verify_service_token("") is None


def test_an_unset_service_token_never_matches():
    auth = AuthService(database=None, jwt_secret="s", token_ttl_minutes=1, service_tokens={SERVICE_BFF: ""})
    assert auth.verify_service_token("") is None
    assert auth.verify_service_token("anything") is None
