"""Host signing key and hand-over bundle (openssl faked; no Docker)."""

import zipfile
from pathlib import Path

from deploy.ops.host_bundle import PRIVATE_KEY_NAME, HostIntegrationBundle
from deploy.ops.layout import InstallLayout
from deploy.ops.runner import CommandResult

REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_PRIVATE = "-----BEGIN PRIVATE KEY-----\r\nAAAA\r\n-----END PRIVATE KEY-----\r\n"
FAKE_PUBLIC = "-----BEGIN PUBLIC KEY-----\r\r\nBBBB\r\r\n-----END PUBLIC KEY-----\r\r\n"


class FakeOpenssl:
    def __init__(self):
        self.generated = 0

    def run(self, args, **_kwargs):
        if args[1] == "genpkey":
            self.generated += 1
            Path(args[args.index("-out") + 1]).write_text(FAKE_PRIVATE, encoding="utf-8", newline="")
            return CommandResult(0, "", "")
        return CommandResult(0, FAKE_PUBLIC, "")


def test_key_pair_is_generated_once_and_the_bundle_is_filled_in(tmp_path):
    layout = InstallLayout(tmp_path)
    layout.ensure_dirs()
    openssl = FakeOpenssl()
    bundle = HostIntegrationBundle(layout, openssl, REPO_ROOT)

    private = bundle.ensure_keys()
    assert private == "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n"
    assert bundle.public_key_path.read_bytes() == b"-----BEGIN PUBLIC KEY-----\nBBBB\n-----END PUBLIC KEY-----\n"
    assert bundle.ensure_keys() is None and openssl.generated == 1

    env = {"HOST_JWT_ISSUER": "https://www.client.vn", "HOST_JWT_AUDIENCE": "https://chat.client.vn",
           "PUBLIC_DOMAIN_CHAT": "chat.client.vn", "HOST_ORIGIN": "https://www.client.vn"}
    with zipfile.ZipFile(bundle.write(env, private)) as archive:
        names = set(archive.namelist())
        node = archive.read("node/chatbot-token.mjs").decode()
        page = archive.read("host-page.html").decode()
        assert archive.read(PRIVATE_KEY_NAME).decode() == private
    assert {"README.md", "php/chatbot_token.php", "python/chatbot_token.py"} <= names
    assert 'const ISSUER = "https://www.client.vn"' in node and "{{" not in node
    assert "https://chat.client.vn/embed.js" in page
