"""
Demo data: a Vietnam → Germany labour-migration knowledge base and real chats through it.

Usage (from the repository root, with the venv active):

    python -m scripts.seed_demo documents   # create the demo source + documents (skips existing titles)
    # restart the API so its search index picks the new documents up
    python -m scripts.seed_demo chats       # run the demo conversations through the running API

``documents`` writes through ``KnowledgeService`` in this process (no admin login
needed). ``chats`` calls the public chat API like the widget server does, with
``BFF_SERVICE_TOKEN``, so every answer, trace, token cost, rating and handoff is
real. It calls the configured LLM (a few cents).

All content is fictional demo material: the counselling centre does not exist
and every figure is marked as illustrative.
"""

# Standard library imports
import argparse
import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# Third-party imports
import httpx
from dotenv import load_dotenv

load_dotenv()

# Local imports
from config.settings import Config  # noqa: E402
from models.knowledge import ChunkingSpec  # noqa: E402

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "demo_data"
CONVERSATIONS_FILE = DATA_DIR / "conversations.json"
SOURCE_NAME = "lao_dong_duc"
SOURCE_DESCRIPTION = "Demo: thông tin đi Đức làm việc cho người lao động Hà Tĩnh (nội dung giả định)"
SOURCE_PRIORITY = 1.0
CREATED_BY = "seed_demo"
#: Split per "##" section and per "###" FAQ question: one Q&A per chunk, or the reranker scores
#: a question against five answers at once. Sections are short, so the size cap never bites.
DEMO_CHUNKING = ChunkingSpec("heading", {"max_level": 3, "max_chars": 3000})
DEFAULT_API_URL = "http://127.0.0.1:8500"
CHAT_TIMEOUT_SECONDS = 120
#: Visitor ids are "demo-<n>-<random>": valid X-End-User-Id values, one per conversation.
VISITOR_PREFIX = "demo"


class DemoSeeder:
    """Creates the demo knowledge base and replays the demo conversations."""

    def __init__(self, api_url: str, service_token: str):
        """
        Args:
            api_url: Base URL of the running API (for ``chats``).
            service_token: The widget server's ``BFF_SERVICE_TOKEN``.
        """
        self._api_url = api_url.rstrip("/")
        self._service_token = service_token

    # ------------------------------------------------------------------ documents

    async def seed_documents(self) -> int:
        """
        Create the demo source and one text document per ``demo_data/*.md`` file.

        Existing demo documents are kept, and re-chunked when their chunking
        differs from ``DEMO_CHUNKING``.

        Returns:
            How many documents were created or re-chunked.
        """
        from api.container import AppContainer

        container = AppContainer()
        await container.start()
        try:
            knowledge = container.knowledge
            sources = {source.name for source, _count in await knowledge.list_sources()}
            if SOURCE_NAME not in sources:
                await knowledge.create_source(SOURCE_NAME, SOURCE_DESCRIPTION, SOURCE_PRIORITY, True)
                logger.info("Created source %s", SOURCE_NAME)
            existing, _total = await knowledge.list_documents(SOURCE_NAME, None, None, 1000, 0)
            by_title = {document.title: document for document in existing}
            changed = 0
            for path in sorted(DATA_DIR.glob("*.md")):
                text = path.read_text(encoding="utf-8")
                title = self._title(text, path)
                document = by_title.get(title)
                if document is None:
                    await knowledge.create_text_document(
                        SOURCE_NAME, title, text, {"demo": True}, CREATED_BY, DEMO_CHUNKING, auto_approve=True
                    )
                    logger.info("Created document: %s", title)
                elif document.chunking != DEMO_CHUNKING.to_json():
                    await knowledge.rechunk(document.id, DEMO_CHUNKING, discard_manual_edits=False)
                    logger.info("Re-chunked document: %s", title)
                else:
                    logger.info("Skipping unchanged document: %s", title)
                    continue
                changed += 1
            return changed
        finally:
            await container.stop()

    @staticmethod
    def _title(text: str, path: Path) -> str:
        """The file's first ``# `` heading, else its name."""
        for line in text.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return path.stem

    # ------------------------------------------------------------------ chats

    def run_conversations(self) -> Dict[str, int]:
        """
        Send every demo conversation through the chat API, then rate answers and
        leave contact details on handoffs as the conversation file says.

        Returns:
            Counts per answer outcome, plus ``ratings`` and ``contacts``.
        """
        conversations: List[Dict[str, Any]] = json.loads(CONVERSATIONS_FILE.read_text(encoding="utf-8"))
        counts: Dict[str, int] = {"ratings": 0, "contacts": 0}
        with httpx.Client(base_url=self._api_url, timeout=CHAT_TIMEOUT_SECONDS) as client:
            for number, conversation in enumerate(conversations, start=1):
                visitor = f"{VISITOR_PREFIX}-{number}-{uuid.uuid4().hex[:8]}"
                conversation_id: Optional[str] = None
                for turn in conversation["turns"]:
                    answer = self._ask(client, visitor, turn["message"], conversation_id)
                    conversation_id = answer["conversation_id"]
                    outcome = answer["outcome"]
                    counts[outcome] = counts.get(outcome, 0) + 1
                    print(f"[{number}] {turn['message']}\n    -> {outcome}: {answer['text'][:100]}")
                    if "rating" in turn and outcome == "answered":
                        self._rate(client, visitor, answer["message_id"], turn["rating"], turn.get("comment"))
                        counts["ratings"] += 1
                    if "contact" in turn and answer.get("handoff_id"):
                        self._leave_contact(client, visitor, answer["handoff_id"], turn["contact"])
                        counts["contacts"] += 1
        return counts

    def _headers(self, visitor: str) -> Dict[str, str]:
        """Widget-server credentials plus the visitor id."""
        return {"X-Service-Token": self._service_token, "X-End-User-Id": visitor}

    def _ask(self, client: httpx.Client, visitor: str, message: str, conversation_id: Optional[str]) -> Dict[str, Any]:
        """One chat turn; raises on an HTTP error."""
        body: Dict[str, Any] = {"message": message}
        if conversation_id:
            body["conversation_id"] = conversation_id
        response = client.post("/api/v1/chat", json=body, headers=self._headers(visitor))
        response.raise_for_status()
        return response.json()

    def _rate(self, client: httpx.Client, visitor: str, message_id: str, rating: int, comment: Optional[str]) -> None:
        """Thumbs up/down on one answer."""
        body: Dict[str, Any] = {"message_id": message_id, "rating": rating}
        if comment:
            body["comment"] = comment
        client.post("/api/v1/feedback", json=body, headers=self._headers(visitor)).raise_for_status()

    def _leave_contact(self, client: httpx.Client, visitor: str, handoff_id: str, contact: Dict[str, str]) -> None:
        """The visitor's (fictional) contact details on a handoff ticket, with consent."""
        body = {**contact, "consent": True}
        client.post(f"/api/v1/handoffs/{handoff_id}/contact", json=body, headers=self._headers(visitor)).raise_for_status()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["documents", "chats"])
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Running API, for 'chats'")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    seeder = DemoSeeder(args.api_url, Config.Security.BFF_SERVICE_TOKEN())
    try:
        if args.command == "documents":
            changed = asyncio.run(seeder.seed_documents())
            print(f"Created or re-chunked {changed} demo documents in '{SOURCE_NAME}'. Restart the API to index them.")
        else:
            counts = seeder.run_conversations()
            print(f"Done: {json.dumps(counts, ensure_ascii=False)}")
    except httpx.HTTPError:
        logger.exception("Chat API call failed; is the API running at %s?", args.api_url)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
