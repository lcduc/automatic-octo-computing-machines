"""
Minimal tool-calling orchestrator: rewrite -> let the model pick a tool (or not) -> answer.
"""

# Standard library imports
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

# Local imports
from models.llm import StreamDelta
from .history import recent_history
from .openai_client import OpenAIClientProvider
from .prompts import SystemPrompts
from .query_rewriter import QueryRewriter
from .tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

#: Messages of history replayed into the prompt.
_HISTORY_WINDOW = 12
#: Tool calls executed from a single model decision; extra calls are ignored.
MAX_TOOL_CALLS_PER_TURN = 3


class ToolCallingAgent:
    """
    Runs one tool-calling round, then answers.

    Flow: condense the query with history -> one non-streaming decision call
    with the registered tool schemas -> if the model called a tool, execute
    it and stream a follow-up completion for the final answer; otherwise the
    decision call's own content is already final.
    """

    def __init__(
        self,
        client_provider: OpenAIClientProvider,
        tool_registry: ToolRegistry,
        query_rewriter: QueryRewriter,
    ):
        """
        Args:
            client_provider: Shared OpenAI client owner.
            tool_registry: Tools available to the model; may be empty, in
                which case this behaves as a plain (rewritten-query) chat call.
            query_rewriter: Condenses follow-ups into standalone queries.
        """
        self._client_provider = client_provider
        self._tool_registry = tool_registry
        self._query_rewriter = query_rewriter

    @staticmethod
    def _build_messages(query: str, history: Optional[List[Dict[str, str]]]) -> List[Dict[str, Any]]:
        """Assemble the system prompt, recent history, and the user's turn."""
        return [
            {"role": "system", "content": SystemPrompts.TOOL_CALLING},
            *recent_history(history, _HISTORY_WINDOW),
            {"role": "user", "content": query},
        ]

    def _execute_tool_call(self, tool_call: Any) -> str:
        """Parse a model tool call's JSON arguments and dispatch it through the registry."""
        try:
            arguments = json.loads(tool_call.function.arguments or "{}")
        except (TypeError, ValueError):
            logger.warning(
                "Malformed tool call arguments for %r: %r",
                tool_call.function.name,
                tool_call.function.arguments,
            )
            return f"Error: arguments for '{tool_call.function.name}' were not valid JSON."
        return self._tool_registry.execute(tool_call.function.name, arguments)

    @staticmethod
    def _assistant_tool_call_message(message: Any, tool_calls: List[Any]) -> Dict[str, Any]:
        """Re-serialize the assistant's tool-call message for the follow-up request."""
        return {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {"name": tool_call.function.name, "arguments": tool_call.function.arguments},
                }
                for tool_call in tool_calls
            ],
        }

    async def stream(
        self, query: str, history: Optional[List[Dict[str, str]]] = None
    ) -> AsyncGenerator[StreamDelta, None]:
        """
        Answer a query, letting the model call a registered tool first if it chooses to.

        Args:
            query: Current turn's user text.
            history: Prior conversation turns, most recent last.

        Yields:
            Text deltas and usage deltas (one per LLM call made).

        Raises:
            Exception: Provider failures propagate to the caller, which maps
                them to a user-facing error instead of streaming raw text.
        """
        standalone_query, rewrite_usage = await self._query_rewriter.rewrite(query, history)
        if rewrite_usage is not None:
            yield StreamDelta(usage=rewrite_usage)
        messages = self._build_messages(standalone_query, history)

        message, decision_usage = await self._client_provider.complete_with_tools_async(
            messages, tools=self._tool_registry.schemas()
        )
        if decision_usage is not None:
            yield StreamDelta(usage=decision_usage)

        if not message.tool_calls:
            yield StreamDelta(text=message.content or "")
            return

        tool_calls = list(message.tool_calls)[:MAX_TOOL_CALLS_PER_TURN]
        messages.append(self._assistant_tool_call_message(message, tool_calls))
        for tool_call in tool_calls:
            logger.info("Executing tool %s", tool_call.function.name)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": self._execute_tool_call(tool_call),
                }
            )

        async for delta in self._client_provider.stream(messages):
            yield delta
