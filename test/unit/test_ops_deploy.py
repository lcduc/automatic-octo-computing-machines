"""Ops CLI actions against a fake Docker: deploy/rollback, backups, preflight and the security self-check."""

import json
from datetime import datetime, timezone

import pytest

from deploy.ops.backup import BackupManager
from deploy.ops.backup_target import BackupTarget
from deploy.ops.compose import Compose
from deploy.ops.deployer import Deployer, DeployError
from deploy.ops.env_file import EnvFile
from deploy.ops.https_probe import ProbeResponse
from deploy.ops.layout import InstallLayout
from deploy.ops.preflight import Preflight
from deploy.ops.runner import CommandError, CommandResult
from deploy.ops.secret_generator import GENERATED_SECRETS
from deploy.ops.security_check import SecuritySelfCheck

HEALTHY = [
    {"Service": name, "State": "running", "Health": "healthy" if name in ("postgres", "api") else "", "Name": f"chatbot-{name}-1",
     "Publishers": [{"PublishedPort": 443}, {"PublishedPort": 80}] if name == "caddy" else []}
    for name in ("postgres", "api", "web", "admin", "caddy")
]


class FakeRunner:
    """Records commands; answers them from ``rules`` (substring of the joined command -> result)."""

    def __init__(self, rules=None):
        self.calls = []
        self.rules = rules or {}

    def run(self, args, env=None, input_text=None, stdin_path=None, stdout_path=None, check=True, timeout=0):
        joined = " ".join(args)
        self.calls.append(joined)
        if stdout_path is not None:
            stdout_path.write_bytes(b"dump")
        for fragment, result in self.rules.items():
            if fragment in joined:
                if isinstance(result, Exception):
                    raise result
                return result
        if "ps --all --format json" in joined:
            return CommandResult(0, "\n".join(json.dumps(item) for item in HEALTHY), "")
        return CommandResult(0, "", "")

    def ran(self, fragment):
        return [call for call in self.calls if fragment in call]


def _install(tmp_path, runner):
    layout = InstallLayout(tmp_path)
    layout.ensure_dirs()
    env = EnvFile(layout.env_file)
    env.set("POSTGRES_APP_PASSWORD", "p" * 40)
    env.save("test")
    compose = Compose(layout, runner, sleep=lambda _: None)
    return layout, compose


def _backups(layout, compose, runner):
    target = BackupTarget.parse("/mnt/backups")
    return BackupManager(layout, compose, runner, target, keep_days=30,
                         now=lambda: datetime(2026, 9, 28, 2, 0, tzinfo=timezone.utc))


def test_deploy_backs_up_ensures_the_app_role_and_records_history(tmp_path):
    runner = FakeRunner()
    layout, compose = _install(tmp_path, runner)
    deployer = Deployer(layout, compose, lambda: _backups(layout, compose, runner), out=lambda _: None)

    result = deployer.deploy("v1.0.0")
    assert result.backup_name == "20260928T020000Z-pre-v1.0.0"
    assert EnvFile(layout.env_file).load().get("IMAGE_TAG") == "v1.0.0"
    assert runner.ran("pg_dump -U chatbot -d chatbot -Fc")
    assert runner.ran(f"--env POSTGRES_APP_PASSWORD={'p' * 40} postgres sh /docker-entrypoint-initdb.d/10-app-role.sh")
    # Backup happens before the new release's containers (and migrations) start.
    assert runner.calls.index(runner.ran("pg_dump")[0]) < runner.calls.index(runner.ran("up --detach --remove-orphans")[-1])

    deployer.deploy("v1.1.0")
    assert deployer.history() == ["v1.0.0", "v1.1.0"] and deployer.previous_tag() == "v1.0.0"
    assert deployer.rollback().tag == "v1.0.0"


def test_failed_deploy_explains_how_to_roll_back(tmp_path):
    runner = FakeRunner()
    layout, compose = _install(tmp_path, runner)
    deployer = Deployer(layout, compose, lambda: None, out=lambda _: None)
    deployer.deploy("v1.0.0")
    runner.rules = {"up --detach --remove-orphans": CommandError("migrate exited 1")}
    with pytest.raises(DeployError, match="chatbot rollback v1.0.0"):
        deployer.deploy("v2.0.0")
    assert deployer.history() == ["v1.0.0"]
    with pytest.raises(DeployError, match="Invalid image tag"):
        deployer.deploy("bad tag")


def test_backup_ships_dump_and_uploads_then_prunes_old_remote_copies(tmp_path):
    runner = FakeRunner()
    layout, compose = _install(tmp_path, runner)
    (layout.uploads_dir / "doc.pdf").write_bytes(b"%PDF")
    backup = _backups(layout, compose, runner).create("nightly")
    assert backup.dump.read_bytes() == b"dump" and backup.uploads.exists()
    copies = runner.ran("rclone copyto")
    assert any(call.endswith("/mnt/backups/20260928T020000Z-nightly.dump") for call in copies)
    assert any(call.endswith("/mnt/backups/20260928T020000Z-nightly-uploads.tar.gz") for call in copies)
    assert runner.ran("rclone delete --min-age 30d /mnt/backups")


def test_preflight_reports_each_failing_prerequisite(tmp_path):
    runner = FakeRunner({
        "nvidia-smi": CommandResult(0, "NVIDIA GeForce GTX 1660 SUPER, 6144, 5000\n", ""),
        "test-alert": CommandError("ALERT_CHANNEL is not configured"),
    })
    layout, compose = _install(tmp_path, runner)
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       16303376 kB\n")
    env = {"PUBLIC_DOMAIN_CHAT": "chat.client.vn", "PUBLIC_DOMAIN_ADMIN": "admin.client.vn"}
    preflight = Preflight(layout, runner, compose, env, {"PREFLIGHT_MIN_FREE_DISK_GB": "0"},
                          lambda: _backups(layout, compose, runner),
                          resolve=lambda domain: ["203.0.113.7"] if domain.startswith("chat") else [],
                          meminfo_path=meminfo)
    results = {result.name: result for result in preflight.run()}
    assert not results["gpu"].ok and "5000 MB free" in results["gpu"].detail
    assert results["memory"].ok
    assert results["dns chat.client.vn"].ok and not results["dns admin.client.vn"].ok
    assert results["backup target"].ok
    assert not results["alert channel"].ok


class FakeProbe:
    def __init__(self, responses):
        self.responses = responses

    def get(self, domain, path):
        return self.responses[(domain, path)]


def _probe_responses(widget_csp):
    secure = {"strict-transport-security": "max-age=31536000"}
    return {
        ("chat.client.vn", "/widget"): ProbeResponse(200, {**secure, "content-security-policy": widget_csp}),
        ("chat.client.vn", "/api/v1/widget/config"): ProbeResponse(404, {}),
        ("chat.client.vn", "/health/ready"): ProbeResponse(404, {}),
        ("admin.client.vn", "/"): ProbeResponse(200, {**secure, "x-frame-options": "DENY",
                                                      "content-security-policy": "default-src 'self'; frame-ancestors 'none'"}),
        ("admin.client.vn", "/api/v1/widget/config"): ProbeResponse(404, {}),
        ("admin.client.vn", "/api/v1/admin/auth/me"): ProbeResponse(401, {}),
    }


def test_security_self_check_passes_on_a_correct_stack_and_catches_leaks(tmp_path):
    runner = FakeRunner({
        "network inspect chatbot_internal": CommandResult(0, "true\n", ""),
        "inspect chatbot-postgres-1": CommandResult(0, json.dumps({"chatbot_internal": {}}), ""),
    })
    layout, compose = _install(tmp_path, runner)
    layout.owner_password_file.write_text("o" * 40)
    env = {**{name: "s" * 48 for name in GENERATED_SECRETS},
           "PUBLIC_DOMAIN_CHAT": "chat.client.vn", "PUBLIC_DOMAIN_ADMIN": "admin.client.vn", "HOST_ORIGIN": "https://www.client.vn"}
    good = SecuritySelfCheck(layout, runner, compose, env, FakeProbe(_probe_responses("frame-ancestors 'self' https://www.client.vn")))
    failures = [result for result in good.run() if not result.ok]
    assert failures == []

    leaky = SecuritySelfCheck(layout, runner, compose, {**env, "BFF_SERVICE_TOKEN": "change-me"},
                              FakeProbe(_probe_responses("frame-ancestors *")))
    failed = {result.name for result in leaky.run() if not result.ok}
    assert failed == {"secrets", "widget framing"}
