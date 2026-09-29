"""
Golden evaluation set collected from real answers (ADM-12, RET-R3).

A case copies the question, the expected answer and the cited documents with
personal data masked, and keeps no id of the conversation or message, so
retention purges and deletion requests never have to reach it.
"""

# Standard library imports
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

# Third-party imports
from sqlalchemy import func, select

# Local imports
from core.guardrails.pii_redactor import PiiRedactor
from core.storage.conversation_repository import ConversationRepository
from core.storage.database import Database
from core.storage.tables.eval_tables import EvalCase
from .errors import InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)


class EvalCaseService:
    """Creates, lists, deletes and exports eval cases."""

    def __init__(self, database: Database, redactor: Optional[PiiRedactor] = None):
        """
        Args:
            database: Connected database.
            redactor: Masks personal data; always applied, whatever the chat-log redaction setting.
        """
        self._database = database
        self._redactor = redactor or PiiRedactor()

    def _clean(self, text: str) -> str:
        """The text with personal data masked."""
        return self._redactor.redact(text).text

    async def create_from_message(
        self, message_id: uuid.UUID, expected_answer: Optional[str], note: Optional[str], created_by: str
    ) -> EvalCase:
        """
        Copy an assistant answer and its question into the eval set.

        Args:
            message_id: The assistant message.
            expected_answer: The correct answer; defaults to the bot's answer.
            note: Why the case was added.
            created_by: Admin e-mail.

        Raises:
            NotFoundError: Unknown message, or not an assistant answer.
            InvalidRequestError: No question precedes the answer.
        """
        async with self._database.session() as session:
            repository = ConversationRepository(session)
            message = await repository.get_message(message_id)
            if message is None or message.role != "assistant":
                raise NotFoundError("Answer not found")
            question = (await repository.questions_for([message])).get(message.id)
            if not question:
                raise InvalidRequestError("No question precedes this answer")
            citations = message.citations or []
            case = EvalCase(
                question=self._clean(question),
                expected_answer=self._clean(expected_answer or message.content),
                expected_sources=list(dict.fromkeys(c.get("title", "") for c in citations if c.get("title"))),
                document_ids=list(dict.fromkeys(c.get("document_id", "") for c in citations if c.get("document_id"))),
                note=self._clean(note) if note else None,
                created_by=created_by,
            )
            session.add(case)
        logger.info("Eval case %s added by %s", case.id, created_by)
        return case

    async def list(self, limit: int, offset: int) -> Tuple[List[EvalCase], int]:
        """Eval cases newest first, with the total count."""
        async with self._database.session() as session:
            total = (await session.execute(select(func.count(EvalCase.id)))).scalar_one()
            result = await session.execute(select(EvalCase).order_by(EvalCase.created_at.desc()).limit(limit).offset(offset))
            return list(result.scalars().all()), int(total)

    async def delete(self, case_id: uuid.UUID) -> None:
        """
        Raises:
            NotFoundError: Unknown case.
        """
        async with self._database.session() as session:
            case = await session.get(EvalCase, case_id)
            if case is None:
                raise NotFoundError("Eval case not found")
            await session.delete(case)
        logger.info("Eval case %s deleted", case_id)

    async def export(self) -> List[Dict[str, Any]]:
        """Every case in the ``golden_queries.json`` format read by ``scripts/eval_rag.py``."""
        async with self._database.session() as session:
            cases = (await session.execute(select(EvalCase).order_by(EvalCase.created_at))).scalars().all()
        return [
            {
                "query": case.question,
                "expected_source": case.expected_sources[0] if case.expected_sources else "",
                "expected_sources": case.expected_sources,
                "expected_answer": case.expected_answer,
                "document_ids": case.document_ids,
            }
            for case in cases
        ]
