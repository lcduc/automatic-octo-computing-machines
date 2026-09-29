"""
Post-deploy security self-check (part of ``chatbot preflight``).

Verifies, on the running stack, what the install model promises: only Caddy
publishes ports (80/443); the database and internal services sit on an
internal-only network; the security headers are present on both domains; no
API route other than the admin API is reachable from outside; and no
generated secret is missing, short or a copied example value.

An external port scan (e.g. ``nmap`` from another host) is still the final
word on the firewall; this check covers everything under our control.
"""

# Standard library imports
import json
import logging
from typing import Dict, List

# Local imports
from .check_result import CheckResult
from .compose import Compose
from .https_probe import HttpsProbe, ProbeError
from .layout import COMPOSE_PROJECT, InstallLayout
from .runner import CommandError, CommandRunner
from .secret_generator import GENERATED_SECRETS

logger = logging.getLogger(__name__)

#: The only service allowed to publish ports, and the only ports it may publish.
PUBLIC_SERVICE = "caddy"
PUBLIC_PORTS = {80, 443}
#: Services that must be attached to nothing but the internal network.
INTERNAL_ONLY_SERVICES = ("postgres", "model-server")
INTERNAL_NETWORK = f"{COMPOSE_PROJECT}_internal"
MIN_SECRET_LENGTH = 32
#: Placeholder fragments that must never survive into a real .env.
EXAMPLE_MARKERS = ("change-me", "changeme", "example")


class SecuritySelfCheck:
    """Checks the running stack against the install's security model."""

    def __init__(self, layout: InstallLayout, runner: CommandRunner, compose: Compose,
                 env: Dict[str, str], probe: HttpsProbe):
        """
        Args:
            layout: The install directory.
            runner: Runs ``docker``.
            compose: Compose for the stack.
            env: Values of ``.env``.
            probe: HTTPS client for this box's domains.
        """
        self._layout = layout
        self._runner = runner
        self._compose = compose
        self._env = env
        self._probe = probe

    def run(self) -> List[CheckResult]:
        """Every check, in order."""
        return [
            self.check_secrets(),
            *self.check_published_ports(),
            self.check_internal_network(),
            *self.check_chat_domain(),
            *self.check_admin_domain(),
        ]

    def check_secrets(self) -> CheckResult:
        """Every generated secret is present, long and not an example value."""
        weak = [name for name in GENERATED_SECRETS if _weak(self._env.get(name, ""))]
        owner = self._layout.owner_password_file
        if not owner.exists() or _weak(owner.read_text(encoding="utf-8").strip()):
            weak.append("postgres owner password")
        return CheckResult("secrets", not weak, "all generated" if not weak else f"weak or missing: {', '.join(weak)}")

    def check_published_ports(self) -> List[CheckResult]:
        """Only caddy publishes ports, and only 80/443."""
        try:
            containers = self._compose.ps()
        except CommandError as exc:
            return [CheckResult("published ports", False, str(exc)[:300])]
        problems = []
        for container in containers:
            published = {item.get("PublishedPort") for item in container.get("Publishers") or [] if item.get("PublishedPort")}
            service = container.get("Service")
            allowed = PUBLIC_PORTS if service == PUBLIC_SERVICE else set()
            if published - allowed:
                problems.append(f"{service} publishes {sorted(published - allowed)}")
        return [CheckResult("published ports", not problems, "only caddy on 80/443" if not problems else "; ".join(problems))]

    def check_internal_network(self) -> CheckResult:
        """The internal network has no route out, and internal-only services use nothing else."""
        try:
            internal = self._runner.run(["docker", "network", "inspect", INTERNAL_NETWORK, "--format", "{{.Internal}}"]).stdout.strip()
            problems = [] if internal == "true" else [f"{INTERNAL_NETWORK} is not internal"]
            for container in self._compose.ps():
                if container.get("Service") in INTERNAL_ONLY_SERVICES:
                    networks = json.loads(self._runner.run(
                        ["docker", "inspect", container["Name"], "--format", "{{json .NetworkSettings.Networks}}"]
                    ).stdout or "{}")
                    extra = sorted(set(networks) - {INTERNAL_NETWORK})
                    if extra:
                        problems.append(f"{container['Service']} is also on {', '.join(extra)}")
        except (CommandError, ValueError, KeyError) as exc:
            return CheckResult("internal network", False, str(exc)[:300])
        return CheckResult("internal network", not problems, "database unreachable from outside" if not problems else "; ".join(problems))

    def _get(self, domain: str, path: str):
        """One probe; a failure becomes ``None`` so the calling check reports it."""
        try:
            return self._probe.get(domain, path)
        except ProbeError:
            logger.exception("Probe of https://%s%s failed", domain, path)
            return None

    def check_chat_domain(self) -> List[CheckResult]:
        """The widget is frameable only by the host site; the API is not exposed."""
        domain = self._env.get("PUBLIC_DOMAIN_CHAT", "")
        widget = self._get(domain, "/widget")
        if widget is None:
            return [CheckResult(f"https {domain}", False, "unreachable over verified TLS")]
        csp = widget.headers.get("content-security-policy", "")
        origins = self._env.get("HOST_ORIGIN", "").split()
        framing_ok = "frame-ancestors" in csp and all(origin in csp for origin in origins) and "*" not in csp
        results = [
            CheckResult(f"https {domain}", widget.status == 200, f"/widget answered {widget.status} with a valid certificate"),
            CheckResult("widget framing", framing_ok, f"frame-ancestors limited to {' '.join(origins) or '(none)'}"),
            CheckResult("chat HSTS", "strict-transport-security" in widget.headers, "Strict-Transport-Security present"),
        ]
        for path in ("/api/v1/widget/config", "/health/ready"):
            response = self._get(domain, path)
            hidden = response is not None and response.status == 404
            results.append(CheckResult(f"chat {path} hidden", hidden, f"answered {response.status if response else 'nothing'}"))
        return results

    def check_admin_domain(self) -> List[CheckResult]:
        """The admin web is never frameable; only the admin API is reachable there."""
        domain = self._env.get("PUBLIC_DOMAIN_ADMIN", "")
        page = self._get(domain, "/")
        if page is None:
            return [CheckResult(f"https {domain}", False, "unreachable over verified TLS")]
        csp = page.headers.get("content-security-policy", "")
        results = [
            CheckResult(f"https {domain}", page.status == 200, f"/ answered {page.status} with a valid certificate"),
            CheckResult("admin not frameable", "frame-ancestors 'none'" in csp and page.headers.get("x-frame-options") == "DENY",
                        "frame-ancestors 'none' and X-Frame-Options DENY"),
            CheckResult("admin HSTS", "strict-transport-security" in page.headers, "Strict-Transport-Security present"),
        ]
        public_api = self._get(domain, "/api/v1/widget/config")
        results.append(CheckResult("admin /api/v1 hidden", public_api is not None and public_api.status == 404,
                                   f"public API answered {public_api.status if public_api else 'nothing'}"))
        admin_api = self._get(domain, "/api/v1/admin/auth/me")
        results.append(CheckResult("admin API behind sign-in", admin_api is not None and admin_api.status == 401,
                                   f"answered {admin_api.status if admin_api else 'nothing'}"))
        return results


def _weak(value: str) -> bool:
    """Too short, or containing a placeholder fragment."""
    return len(value) < MIN_SECRET_LENGTH or any(marker in value.lower() for marker in EXAMPLE_MARKERS)
