"""
Operator CLI for first-time setup.

Usage (from the repository root, with the venv active):

    python -m scripts.manage create-admin --email you@example.com --role owner
    python -m scripts.manage create-api-key --name "vieclamhatinh web"

The admin password is prompted for (never passed on the command line). The
API key is printed once; put it in the frontend's ``CHATBOT_API_KEY``.
"""

# Standard library imports
import argparse
import asyncio
import getpass
import sys

# Third-party imports
from dotenv import load_dotenv

load_dotenv()

# Local imports
from config.settings import Config  # noqa: E402
from core.storage.database import Database  # noqa: E402
from services.auth_service import AuthService  # noqa: E402
from services.errors import ServiceError  # noqa: E402


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

    async def create_api_key(self, name: str) -> None:
        """Issue a chat API key and print it once."""
        record, raw_key = await self._auth.create_api_key(name)
        print(f"API key for '{record.name}' (shown once, store it now):\n{raw_key}")

    async def run(self, args: argparse.Namespace) -> None:
        """Dispatch the parsed command."""
        self._database.connect()
        try:
            if args.command == "create-admin":
                await self.create_admin(args.email, args.role)
            elif args.command == "create-api-key":
                await self.create_api_key(args.name)
        finally:
            await self._database.close()


def _parser() -> argparse.ArgumentParser:
    """Command-line interface definition."""
    parser = argparse.ArgumentParser(description="Chatbot management commands")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="Create an admin account for the management web")
    admin.add_argument("--email", required=True)
    admin.add_argument("--role", choices=["owner", "editor", "viewer"], default="owner")
    key = commands.add_parser("create-api-key", help="Issue an API key for a chat frontend")
    key.add_argument("--name", required=True)
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
