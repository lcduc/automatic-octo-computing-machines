"""
Write the API's OpenAPI schema to docs/openapi.json (the machine-readable twin of docs/API.md).

Usage (from the repository root, with the venv active):

    python -m scripts.export_openapi

Builds the FastAPI app without starting it (no database or models are needed)
and dumps ``app.openapi()``; re-run it whenever a route or schema changes.
"""

# Standard library imports
import json
import sys
from pathlib import Path

# Third-party imports
from dotenv import load_dotenv

load_dotenv()

# Local imports
from main import create_app  # noqa: E402

OUTPUT_PATH = Path("docs/openapi.json")


def main() -> None:
    """Export the schema and report where it was written."""
    schema = create_app().openapi()
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Intentional CLI output.
    print(f"Wrote {OUTPUT_PATH} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    sys.exit(main())
