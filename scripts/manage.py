"""
Operator CLI for first-time setup.

Usage (from the repository root, with the venv active, or inside the api container):

    python -m scripts.manage create-admin --email you@example.com --role owner
    python -m scripts.manage create-api-key --name "client backend"
    python -m scripts.manage bootstrap-admin --email you@example.com
    python -m scripts.manage test-alert
    python -m scripts.manage send-alert --subject "Backup failed" --body "..."
    python -m scripts.manage sync-sql-tools --file deploy/business_db/demo_tools.json
    python -m scripts.manage check-business-db

``create-admin`` prompts for the password (never passed on the command line).
``bootstrap-admin`` is what the installer runs: it creates the first owner with
a generated one-time password, printed once as JSON, and does nothing when an
admin already exists. ``test-alert`` sends one message to the configured alert
channel and exits non-zero if it cannot; ``send-alert`` sends any message (the ops CLI
uses it when an unattended backup fails). API keys are for server-to-server
integrations; the chat widget's server authenticates with its generated
service token instead.
"""

# Standard library imports
import argparse
import asyncio
import getpass
import json
import secrets
import sys
from typing import List

# Third-party imports
from dotenv import load_dotenv

load_dotenv()

# Local imports
from config.settings import Config  # noqa: E402
from config.tool_settings import BusinessDbConfig  # noqa: E402
from core.agent.tools.sql_tool_executor import SqlToolExecutor  # noqa: E402
from core.infrastructure.alert_notifier import AlertDeliveryError, AlertNotifier  # noqa: E402
from core.storage.business_db_probe import BusinessDbProbe  # noqa: E402
from core.storage.database import Database  # noqa: E402
from core.storage.tables.access_tables import ADMIN_ROLES, API_KEY_SCOPES, ROLE_OWNER, SCOPE_CHAT  # noqa: E402
from services.auth_service import AuthService  # noqa: E402
from services.host_identity_service import HostIdentityService  # noqa: E402
from services.sql_tool_catalog import SqlToolCatalog  # noqa: E402
from services.errors import ServiceError  # noqa: E402

#: Bytes of randomness in a generated one-time admin password (~22 URL-safe characters).
BOOTSTRAP_PASSWORD_BYTES = 16
TEST_ALERT_SUBJECT = "Test alert"
TEST_ALERT_BODY = "The chatbot can reach this alert channel. No action is needed."


class ManagementCli:
    """Runs one management command against the configured database."""

    def __init__(self, database: Database):
        """
        Args:
            database: Not yet connected database.
        """
        self._database = database
        self._auth = AuthService(database, Config.Security.ADMIN_JWT_SECRET() or "cli", 1)

    async def create_admin(self, email: str, role: str) -> None:
        """Prompt for a password and create the account."""
        password = getpass.getpass("Password (min 10 characters): ")
        if password != getpass.getpass("Repeat password: "):
            raise ServiceError("Passwords do not match")
        user = await self._auth.create_admin(email, password, role)
        print(f"Created {user.role} account {user.email}")

    async def bootstrap_admin(self, email: str) -> None:
        """Create the first owner with a generated password, unless any admin exists."""
        if await self._auth.list_admins():
            print(json.dumps({"created": False}))
            return
        password = secrets.token_urlsafe(BOOTSTRAP_PASSWORD_BYTES)
        user = await self._auth.create_admin(email, password, ROLE_OWNER)
        # Intentional CLI output: the installer shows this password once and never stores it.
        print(json.dumps({"created": True, "email": user.email, "password": password}))

    async def create_api_key(self, name: str, scopes: List[str]) -> None:
        """Issue a server-to-server API key and print it once."""
        record, raw_key = await self._auth.create_api_key(name, scopes)
        print(f"API key for '{record.name}' ({', '.join(record.scopes)}; shown once, store it now):\n{raw_key}")

    @staticmethod
    async def send_alert(subject: str, body: str) -> str:
        """
        Send one message to the configured alert channel.

        Returns:
            The channel used.

        Raises:
            ServiceError: No channel is configured or delivery failed.
        """
        notifier = AlertNotifier.from_config()
        if not notifier.enabled:
            raise ServiceError("ALERT_CHANNEL is not configured")
        try:
            await notifier.send(subject, body)
        except AlertDeliveryError as exc:
            raise ServiceError(str(exc)) from exc
        return notifier.channel

    async def test_alert(self) -> None:
        """Send the preflight's test message."""
        print(f"Test alert sent via {await self.send_alert(TEST_ALERT_SUBJECT, TEST_ALERT_BODY)}")

    async def sync_sql_tools(self, path: str) -> None:
        """
        Create or update SQL tool definitions from a JSON file (enabled flags are kept).

        Raises:
            ServiceError: Unreadable file or an invalid definition.
        """
        try:
            with open(path, encoding="utf-8") as handle:
                definitions = json.load(handle)
        except (OSError, ValueError) as exc:
            raise ServiceError(f"Cannot read {path}: {exc}") from exc
        catalog = SqlToolCatalog(self._database, SqlToolExecutor(None, 0), HostIdentityService.from_config(None).tier_level)
        names = await catalog.sync(definitions, "cli")
        print(f"Synced SQL tools: {', '.join(names)}")

    @staticmethod
    async def check_business_db() -> None:
        """
        Prove the business database role can read but never write (TOOL-05).

        Raises:
            ServiceError: Not configured, unreachable, or the role can write.
        """
        url = BusinessDbConfig.BUSINESS_DB_URL()
        if not url:
            raise ServiceError("BUSINESS_DB_URL is not configured")
        problems = await BusinessDbProbe(url).problems()
        if problems:
            raise ServiceError("Business database role is not read-only: " + "; ".join(problems))
        print("Business database role is read-only")

    async def run(self, args: argparse.Namespace) -> None:
        """Dispatch the parsed command."""
        if args.command == "test-alert":
            await self.test_alert()
            return
        if args.command == "send-alert":
            print(f"Alert sent via {await self.send_alert(args.subject, args.body)}")
            return
        if args.command == "check-business-db":
            await self.check_business_db()
            return
        self._database.connect()
        try:
            if args.command == "create-admin":
                await self.create_admin(args.email, args.role)
            elif args.command == "bootstrap-admin":
                await self.bootstrap_admin(args.email)
            elif args.command == "sync-sql-tools":
                await self.sync_sql_tools(args.file)
            elif args.command == "create-api-key":
                await self.create_api_key(args.name, args.scope or [SCOPE_CHAT])
        finally:
            await self._database.close()


def _parser() -> argparse.ArgumentParser:
    """Command-line interface definition."""
    parser = argparse.ArgumentParser(description="Chatbot management commands")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="Create an admin account for the management web")
    admin.add_argument("--email", required=True)
    admin.add_argument("--role", choices=list(ADMIN_ROLES), default=ROLE_OWNER)
    bootstrap = commands.add_parser("bootstrap-admin", help="Create the first owner with a one-time password")
    bootstrap.add_argument("--email", required=True)
    key = commands.add_parser("create-api-key", help="Issue an API key for a server-to-server integration")
    key.add_argument("--name", required=True)
    key.add_argument("--scope", action="append", choices=list(API_KEY_SCOPES),
                     help="Repeat for several scopes (default: chat)")
    commands.add_parser("test-alert", help="Send a test message to the configured alert channel")
    alert = commands.add_parser("send-alert", help="Send an operator alert (used by the ops CLI, e.g. a failed backup)")
    alert.add_argument("--subject", required=True)
    alert.add_argument("--body", default="")
    tools = commands.add_parser("sync-sql-tools", help="Create or update SQL tool definitions from a JSON file")
    tools.add_argument("--file", required=True)
    commands.add_parser("check-business-db", help="Check the business database role cannot write")
    return parser


def main() -> None:
    """Entry point."""
    args = _parser().parse_args()
    cli = ManagementCli(Database(Config.Database.DATABASE_URL(), pool_size=1))
    try:
        asyncio.run(cli.run(args))
    except ServiceError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
