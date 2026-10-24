"""
Generate synthetic Vietnamese questions for every knowledge chunk with the configured LLM.

For each chunk the LLM writes questions in three styles (formal, colloquial, unaccented) that the
chunk alone answers. The output feeds ``scripts.filter_synthetic_queries`` and then the retrieval
training scripts; the human golden sets are never shown to the LLM.

The provider, key and model come from the usual settings (``LLM_PROVIDER``, ``OPENAI_API_KEY`` /
``ANTHROPIC_API_KEY`` / ``GEMINI_API_KEY``, ``--model``). Usage (from the repository root)::

    python -m scripts.generate_synthetic_queries --dry-run            # export the corpus, show one prompt
    python -m scripts.generate_synthetic_queries --model <model> --limit 3   # pilot on three chunks
    python -m scripts.generate_synthetic_queries --model <model>
"""

# Standard library imports
import argparse
import asyncio
import json
import logging
import re
import sys
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

# Third-party imports
from dotenv import load_dotenv

load_dotenv()

# Local imports
from config.settings import Config  # noqa: E402
from core.storage.database import Database  # noqa: E402
from core.storage.knowledge_repository import KnowledgeRepository  # noqa: E402
from scripts.synthetic_dataset import CORPUS_FILE, RAW_QUESTIONS_FILE, read_jsonl, write_jsonl  # noqa: E402

logger = logging.getLogger(__name__)

#: Questions requested per style; the filter keeps at most ``MAX_KEPT_PER_CHUNK`` of the six.
QUESTIONS_PER_STYLE = {"formal": 2, "colloquial": 2, "unaccented": 2}
STYLES = tuple(QUESTIONS_PER_STYLE)
DEFAULT_CONCURRENCY = 4
#: One more attempt when a reply is not the JSON asked for.
PARSE_ATTEMPTS = 2
JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM_PROMPT = f"""You write realistic questions in Vietnamese that a worker from Hà Tĩnh province, thinking about working in Germany, would type into the chat widget of a labour-migration counselling centre.

You are given one passage of the centre's knowledge base. Write exactly {sum(QUESTIONS_PER_STYLE.values())} questions that this passage answers:
- {QUESTIONS_PER_STYLE['formal']} "formal": standard written Vietnamese with full diacritics, polite and complete, as in an email to the centre.
- {QUESTIONS_PER_STYLE['colloquial']} "colloquial": spoken chat style with full diacritics, in the first person (em, mình, tôi, cháu); may mention a personal situation (age, job, family, money worries) and use particles such as ạ, nhỉ, vậy, thế, không ạ.
- {QUESTIONS_PER_STYLE['unaccented']} "unaccented": typed without Vietnamese diacritics, casual, may use common chat abbreviations (k, ko, dc, j, bn, ntn); these must be different questions from the others, not a copy with the accents removed.

Rules:
- Each question must be answerable from this passage alone and ask about something specific in it (a figure, condition, step, warning, right or rule), not about the topic in general.
- Do not copy phrases from the passage or its headings; use the words an ordinary worker would use.
- Never mention "the passage", "the document", "the article" or the centre's knowledge base.
- Cover different facts of the passage where possible and vary the question form (what, how much, how long, can I, do I need, what if).
- Each question stands on its own: name what it is about instead of "it" or "that programme".
- 8 to 35 words per question.

Reply with JSON only, no prose: {{"questions": [{{"style": "formal", "question": "..."}}, ...]}}"""


def user_prompt(chunk: Dict[str, Any]) -> str:
    """The chunk as the LLM sees it: its document title, then its text."""
    return f"Tài liệu: {chunk['document_title']}\n\nĐoạn trích:\n{chunk['content']}"


def parse_questions(text: str) -> List[Dict[str, str]]:
    """
    The ``{"style", "question"}`` items of a reply.

    Raises:
        ValueError: When the reply holds no JSON object or no usable question.
    """
    match = JSON_OBJECT.search(text or "")
    if not match:
        raise ValueError("no JSON object in the reply")
    items = json.loads(match.group(0)).get("questions", [])
    questions = [
        {"style": str(item.get("style", "")).strip().lower(), "question": " ".join(str(item.get("question", "")).split())}
        for item in items
        if isinstance(item, dict)
    ]
    questions = [item for item in questions if item["style"] in STYLES and item["question"]]
    if not questions:
        raise ValueError("no question with a known style in the reply")
    return questions


class SyntheticQueryGenerator:
    """Asks the LLM for questions about each chunk, a few chunks at a time."""

    def __init__(self, llm, model: Optional[str], concurrency: int = DEFAULT_CONCURRENCY):
        """
        Args:
            llm: A ``BaseLLMProvider`` (``complete_async(messages, model)``).
            model: Model override; ``None`` uses the provider's configured model.
            concurrency: Requests in flight at once.
        """
        self._llm = llm
        self._model = model
        self._slots = asyncio.Semaphore(max(1, concurrency))
        self._usage = Counter()

    @property
    def usage(self) -> Dict[str, int]:
        """Prompt/completion tokens and calls so far."""
        return dict(self._usage)

    async def generate(self, chunks: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Questions for every chunk.

        Returns:
            ``(records, failed_chunk_ids)``; a chunk whose replies never parsed is reported, not retried forever.
        """
        logger.info("Generating questions for %d chunks", len(chunks))
        results = await asyncio.gather(*(self._for_chunk(chunk) for chunk in chunks))
        records = [record for batch in results for record in batch]
        failed = [chunk["chunk_id"] for chunk, batch in zip(chunks, results) if not batch]
        logger.info("Generated %d questions; %d chunks failed", len(records), len(failed))
        return records, failed

    async def _for_chunk(self, chunk: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The parsed questions of one chunk, or ``[]`` after the last failed attempt."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt(chunk)}]
        async with self._slots:
            for attempt in range(1, PARSE_ATTEMPTS + 1):
                try:
                    result = await self._llm.complete_async(messages, model=self._model)
                    self._record_usage(result.usage)
                    questions = parse_questions(result.text)
                except Exception:
                    logger.exception("Chunk %s, attempt %d failed", chunk["chunk_id"], attempt)
                    continue
                model = result.usage.model if result.usage else self._model
                return [{"chunk_id": chunk["chunk_id"], **item, "model": model} for item in questions]
        return []

    def _record_usage(self, usage) -> None:
        """Add one call's tokens to the running totals."""
        self._usage["calls"] += 1
        if usage is not None:
            self._usage["prompt_tokens"] += usage.prompt_tokens
            self._usage["completion_tokens"] += usage.completion_tokens


async def export_corpus() -> List[Dict[str, Any]]:
    """Read the searchable chunks from the configured database and save them as the dataset corpus."""
    database = Database(Config.Database.DATABASE_URL(), pool_size=1)
    database.connect()
    try:
        async with database.session() as session:
            rows = await KnowledgeRepository(session).load_index_rows()
    finally:
        await database.close()
    corpus = [
        {"chunk_id": str(row.chunk_id), "document_title": row.document_title, "position": row.position, "content": row.content}
        for row in rows
    ]
    write_jsonl(CORPUS_FILE, corpus)
    logger.info("Exported %d chunks to %s", len(corpus), CORPUS_FILE)
    return corpus


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=None, help="Model override for the configured LLM_PROVIDER")
    parser.add_argument("--limit", type=int, default=None, help="Only the first N chunks (a pilot run)")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--dry-run", action="store_true", help="Export the corpus and print one prompt; no LLM call")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    corpus = asyncio.run(export_corpus())
    chunks = corpus[: args.limit] if args.limit else corpus
    if args.dry_run:
        print(f"SYSTEM ({len(SYSTEM_PROMPT)} chars):\n{SYSTEM_PROMPT}\n\nUSER:\n{user_prompt(chunks[0])}\n")
        user_chars = sum(len(user_prompt(chunk)) for chunk in chunks)
        print(f"{len(chunks)} calls; system prompt {len(SYSTEM_PROMPT)} chars per call, user prompts {user_chars} chars in total")
        return 0

    from core.agent.provider_factory import LLMProviderFactory

    generator = SyntheticQueryGenerator(LLMProviderFactory.create(), args.model, args.concurrency)
    records, failed = asyncio.run(generator.generate(chunks))
    if args.limit and RAW_QUESTIONS_FILE.exists():
        # A pilot replaces only its own chunks' questions.
        piloted = {chunk["chunk_id"] for chunk in chunks}
        records = [r for r in read_jsonl(RAW_QUESTIONS_FILE) if r["chunk_id"] not in piloted] + records
    write_jsonl(RAW_QUESTIONS_FILE, records)
    print(f"{len(records)} questions written to {RAW_QUESTIONS_FILE}; usage {generator.usage}")
    if failed:
        print(f"No usable reply for {len(failed)} chunks: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
