"""Audit entries never store secrets, at any nesting depth (no network, no database)."""

from services.audit_service import REDACTED, redact_secrets


def test_secrets_are_redacted_at_any_depth_and_other_values_kept():
    body = {
        "email": "owner@example.test",
        "password": "hunter2-hunter2",
        "admin": {"access_token": "eyJ...", "role": "owner"},
        "keys": [{"name": "web", "key": "sk_live_123"}],
    }

    assert redact_secrets(body) == {
        "email": "owner@example.test",
        "password": REDACTED,
        "admin": {"access_token": REDACTED, "role": "owner"},
        "keys": [{"name": "web", "key": REDACTED}],
    }
    assert redact_secrets(None) is None and redact_secrets("plain") == "plain"
