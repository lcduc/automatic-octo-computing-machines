"""
``chatbot install``: from answers to a running, checked stack in one command.

1. Copy the release's compose file and deploy/ assets into the install directory.
2. Take the answers (file or prompts) and write ``.env`` / ``ops.env`` (0600).
3. Generate every missing secret; keep existing ones (reruns are idempotent).
4. Pull the images and run the preflight checks; stop on any failure.
5. Deploy the tag, create the first owner with a one-time password.
6. Run the security self-check and print what to hand over.
"""

# Standard library imports
import json
import logging
from typing import Optional

# Local imports
from .answers import InstallAnswers
from .check_result import report
from .context import OpsContext
from .deployer import ENV_HEADER
from .env_file import EnvFile
from .host_bundle import HostIntegrationBundle
from .layout import copy_templates
from .prompter import InteractivePrompter
from .secret_generator import SecretGenerator

logger = logging.getLogger(__name__)

OPS_ENV_HEADER = (
    "Read only by the chatbot ops CLI (backups, first admin, preflight thresholds).\n"
    "Never mounted into an application container."
)
APP_ROLE = "chatbot_app"


class InstallError(RuntimeError):
    """The install stopped; the message says why and what to fix."""


class Installer:
    """Runs the install flow for one box."""

    def __init__(self, context: OpsContext, generator: Optional[SecretGenerator] = None,
                 prompter: Optional[InteractivePrompter] = None):
        """
        Args:
            context: The install directory and its collaborators.
            generator: Secret generator (tests pass a deterministic one).
            prompter: Asks the questions when no answers file is given.
        """
        self._context = context
        self._generator = generator or SecretGenerator()
        self._prompter = prompter or InteractivePrompter(out=context.out)

    def configure(self, answers: Optional[InstallAnswers], tag: str, registry: str) -> InstallAnswers:
        """
        Steps 1-3: copy the templates and write validated settings with generated secrets.

        Returns:
            The answers that were applied.

        Raises:
            AnswersError: Invalid answers (nothing is written then).
        """
        layout = self._context.layout
        layout.ensure_dirs()
        copy_templates(self._context.templates_dir, layout.root)
        env = EnvFile(layout.env_file).load()
        ops_env = EnvFile(layout.ops_env_file).load()
        if answers is None:
            answers = self._prompter.collect({**ops_env.as_dict(), **env.as_dict()})
        answers.validate()
        answers.apply(env, ops_env)
        env.setdefault("APP_ENV", "production")
        env.setdefault("POSTGRES_APP_USER", APP_ROLE)
        env.set("REGISTRY", registry)
        env.set("IMAGE_TAG", tag)
        generated = self._generator.ensure(env)
        self._generator.ensure_owner_password(layout)
        env.save(ENV_HEADER)
        ops_env.save(OPS_ENV_HEADER)
        self._context.out(f"Settings written to {layout.env_file} ({len(generated)} secrets generated now).")
        self._hand_over_host_keys(env, "HOST_JWT_SECRET" in generated)
        return answers

    def _hand_over_host_keys(self, env: EnvFile, new_shared_secret: bool) -> None:
        """Generate the host signing key on first install and package it for the host's developers."""
        bundle = HostIntegrationBundle(self._context.layout, self._context.runner, self._context.templates_dir)
        private_key = bundle.ensure_keys()
        mode = env.get("HOST_AUTH_MODE", "rs256")
        shared = env.get("HOST_JWT_SECRET") if mode == "hs256" and new_shared_secret else None
        if (private_key and mode == "rs256" and not env.get("HOST_JWKS_URL")) or shared:
            path = bundle.write(env.as_dict(), private_key if mode == "rs256" else None, shared)
            self._context.out(
                f"Host integration bundle: {path}\n"
                "  It holds the signing key: give it to the host site's developers, then delete it from this box."
            )

    def install(self, answers: Optional[InstallAnswers], tag: str, registry: str, skip_deploy: bool = False) -> None:
        """
        The whole flow.

        Raises:
            AnswersError: Invalid answers.
            InstallError: A preflight check or the security self-check failed.
            DeployError: The deploy failed.
        """
        answers = self.configure(answers, tag, registry)
        if skip_deploy:
            self._context.out("Configuration only (--skip-deploy): run `chatbot deploy <tag>` when ready.")
            return
        out = self._context.out
        out("Pulling images…")
        self._context.compose.pull()
        out("Preflight checks:")
        if not report(self._context.preflight().run(), out):
            raise InstallError("Preflight failed; fix the items marked FAIL and rerun `chatbot install`.")
        self._context.deployer().deploy(tag)
        credentials = self._bootstrap_admin(answers.admin_email)
        out("Security self-check:")
        if not report(self._context.security_check().run(), out):
            raise InstallError("The stack is running but the security self-check failed; see the items marked FAIL.")
        self._summary(answers, credentials)

    def _bootstrap_admin(self, email: str) -> Optional[str]:
        """Create the first owner; returns its one-time password (``None`` when admins already exist)."""
        result = self._context.compose.exec("api", ["python", "-m", "scripts.manage", "bootstrap-admin", "--email", email])
        lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
        if not lines:
            raise InstallError("Could not read the first admin's credentials from bootstrap-admin")
        payload = json.loads(lines[-1])
        return payload.get("password") if payload.get("created") else None

    def _summary(self, answers: InstallAnswers, password: Optional[str]) -> None:
        """What the operator needs, printed once."""
        out = self._context.out
        out("")
        out("Installed and checked.")
        out(f"  Admin web:   https://{answers.admin_domain}")
        if password:
            out(f"  First admin: {answers.admin_email} / {password}")
            out("               (shown once: sign in now and change it)")
        out("  Embed on the host site, before </body>:")
        out(f'    <script src="https://{answers.chat_domain}/embed.js" defer></script>')
        out(f"  Hand-over files: {self._context.layout.handover_dir}")
        out("  Backups run nightly (cron installed by install.sh); `chatbot backup` runs one now.")
