"""Ops CLI settings: .env writing, install answers, backup targets and generated secrets (no Docker)."""

import pytest

from deploy.ops.answers import AnswersError, AnswersFile
from deploy.ops.backup_target import BackupTarget, BackupTargetError
from deploy.ops.env_file import EnvFile, EnvFileError
from deploy.ops.layout import InstallLayout
from deploy.ops.secret_generator import GENERATED_SECRETS, SecretGenerator

VALID_ANSWERS = {
    "chat_domain": "chat.client.vn",
    "admin_domain": "admin.client.vn",
    "host_origin": "https://www.client.vn https://client.vn/",
    "admin_email": "ops@client.vn",
    "openai_api_key": "sk-test",
    "backup": {"target": "s3://backups/chatbot", "s3_access_key_id": "AK", "s3_secret_access_key": "SK", "keep_days": 14},
    "alert": {"channel": "telegram", "telegram_bot_token": "1:abc", "telegram_chat_id": "-100"},
}


def test_env_file_round_trips_and_quotes_values_that_need_it(tmp_path):
    env = EnvFile(tmp_path / ".env")
    env.set("PLAIN", "abc-123_./:@")
    env.set("SPECIAL", "p@ss $HOME #not-a-comment")
    env.save("header")
    text = (tmp_path / ".env").read_text()
    assert "PLAIN=abc-123_./:@" in text and "SPECIAL='p@ss $HOME #not-a-comment'" in text
    loaded = EnvFile(tmp_path / ".env").load()
    assert loaded.get("SPECIAL") == "p@ss $HOME #not-a-comment"
    with pytest.raises(EnvFileError):
        loaded.set("BAD", "it's")
    with pytest.raises(EnvFileError):
        loaded.set("lower", "x")


def test_valid_answers_map_to_app_and_ops_settings(tmp_path):
    answers = AnswersFile.from_mapping(VALID_ANSWERS)
    answers.validate()
    env, ops_env = EnvFile(tmp_path / ".env"), EnvFile(tmp_path / "ops.env")
    answers.apply(env, ops_env)
    assert env.get("HOST_ORIGIN") == "https://www.client.vn https://client.vn"
    assert env.get("PUBLIC_DOMAIN_ADMIN") == "admin.client.vn" and env.get("ALERT_CHANNEL") == "telegram"
    # Backup credentials never reach the application containers' .env.
    assert env.get("BACKUP_S3_SECRET_ACCESS_KEY") is None and ops_env.get("BACKUP_S3_SECRET_ACCESS_KEY") == "SK"
    assert ops_env.get("BACKUP_KEEP_DAYS") == "14"
    # Host sign-in defaults: RS256, issued by the host site for this chat domain.
    assert env.get("HOST_AUTH_MODE") == "rs256"
    assert env.get("HOST_JWT_ISSUER") == "https://www.client.vn" and env.get("HOST_JWT_AUDIENCE") == "https://chat.client.vn"


@pytest.mark.parametrize(
    "change, fragment",
    [
        ({"admin_domain": "chat.client.vn"}, "must differ"),
        ({"host_origin": "http://www.client.vn"}, "https://"),
        ({"host_origin": "https://www.client.vn/path"}, "no path"),
        ({"alert": {"channel": "slack"}}, "slack_webhook_url"),
        ({"backup": {"target": "ftp://x"}}, "backup.target"),
        ({"host_auth": {"mode": "oauth"}}, "host_auth.mode"),
        ({"host_auth": {"jwks_url": "http://host/jwks"}}, "https://"),
    ],
)
def test_invalid_answers_are_all_reported(change, fragment):
    answers = AnswersFile.from_mapping({**VALID_ANSWERS, **change})
    with pytest.raises(AnswersError, match=fragment):
        answers.validate()


def test_answers_file_rejects_unknown_and_missing_keys():
    with pytest.raises(AnswersError, match="unknown: chat_domian"):
        AnswersFile.from_mapping({**VALID_ANSWERS, "chat_domian": "x"})
    incomplete = {key: value for key, value in VALID_ANSWERS.items() if key != "openai_api_key"}
    with pytest.raises(AnswersError, match="missing: openai_api_key"):
        AnswersFile.from_mapping(incomplete)


def test_local_http_origin_is_allowed_for_staging_host_pages():
    answers = AnswersFile.from_mapping({**VALID_ANSWERS, "host_origin": "http://localhost:8080"})
    assert answers.problems() == []


def test_backup_targets_become_rclone_remotes():
    s3 = BackupTarget.parse("s3://bucket/prefix/", s3_access_key_id="AK", s3_secret_access_key="SK",
                            s3_endpoint="https://s3.example.test")
    assert s3.remote == "BACKUP:bucket/prefix"
    assert s3.rclone_env(lambda value: value)["RCLONE_CONFIG_BACKUP_PROVIDER"] == "Other"
    sftp = BackupTarget.parse("sftp://backup@nas.local:2222/srv/chatbot", sftp_password="pw")
    env = sftp.rclone_env(lambda value: f"obscured({value})")
    assert (sftp.host, sftp.port, sftp.user) == ("nas.local", 2222, "backup")
    assert env["RCLONE_CONFIG_BACKUP_PASS"] == "obscured(pw)"
    assert BackupTarget.parse("/mnt/backups/").remote == "/mnt/backups"
    with pytest.raises(BackupTargetError):
        BackupTarget.parse("s3://bucket")
    with pytest.raises(BackupTargetError):
        BackupTarget.parse("sftp://nas.local/x", sftp_password="pw")


def test_secrets_are_generated_once_and_rotation_spares_visitors_by_default(tmp_path):
    counter = iter(range(1000))
    generator = SecretGenerator(lambda size: f"token{next(counter):03d}".ljust(size, "x"))
    env = EnvFile(tmp_path / ".env")
    env.set("ADMIN_JWT_SECRET", "existing" * 8)
    generated = generator.ensure(env)
    assert "ADMIN_JWT_SECRET" not in generated and set(generated) == set(GENERATED_SECRETS) - {"ADMIN_JWT_SECRET"}
    assert generator.ensure(env) == []

    visitor_before = env.get("VISITOR_COOKIE_SECRET")
    rotated = generator.rotate(env)
    assert "VISITOR_COOKIE_SECRET" not in rotated and env.get("VISITOR_COOKIE_SECRET") == visitor_before
    assert env.get("ADMIN_JWT_SECRET") != "existing" * 8

    layout = InstallLayout(tmp_path)
    first = generator.ensure_owner_password(layout)
    assert generator.ensure_owner_password(layout) == first
    assert layout.owner_password_file.read_text() == first
