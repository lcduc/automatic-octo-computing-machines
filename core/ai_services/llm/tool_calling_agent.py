"""
Minimal tool-calling orchestrator: rewrite -> let the model pick a tool (or not) -> answer.

No concrete tool is wired in here — this is the frame the first real tool
gets registered against once a scenario is chosen (see ``tools/``). Not
wired into ``ChatbotService`` yet: an agent with zero registered tools has
no observable behavior to justify touching the live chat path.
"""

# Standard library imports
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

# Local imports
from .openai_client import OpenAIClientProvider
from .query_rewriter import QueryRewriter
from .tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

#: System prompt describing tool-calling behaviour, independent of which
#: tools are actually registered.
_SYSTEM_PROMPT = (
    "Bạn là trợ lý ảo có thể sử dụng các công cụ (tools) được cung cấp khi cần "
    "thiết để trả lời chính xác hơn. Chỉ gọi công cụ khi thực sự cần thiết cho "
    "câu hỏi của người dùng; nếu không cần, hãy trả lời trực tiếp. Câu trả lời "
    "phải cùng ngôn ngữ với người dùng."
)

#: Turns of history replayed into the prompt.
_HISTORY_WINDOW = 20


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
        max_tool_rounds: int = 1,
    ):
        """
        Args:
            client_provider: Shared OpenAI client owner.
            tool_registry: Tools available to the model; may be empty, in
                which case this behaves as a plain (rewritten-query) chat call.
            query_rewriter: Condenses follow-ups into standalone queries.
            max_tool_rounds: Reserved for future multi-round tool chaining.
                Only single-round tool calling is implemented today, since no
                registered tool needs chaining yet; any value other than
                ``1`` is logged and treated as ``1``.
        """
        self._client_provider = client_provider
        self._tool_registry = tool_registry
        self._query_rewriter = query_rewriter
        if max_tool_rounds != 1:
            logger.warning(
                "ToolCallingAgent only implements single-round tool calling; "
                "ignoring max_tool_rounds=%s",
                max_tool_rounds,
            )
        self._max_tool_rounds = 1

    def _build_messages(
        self, query: str, history: Optional[List[Dict[str, str]]]
    ) -> List[Dict[str, Any]]:
        """Assemble the system prompt, recent history, and the user's turn."""
        messages: List[Dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        for message in (history or [])[-_HISTORY_WINDOW:]:
            if isinstance(message, dict) and "role" in message and "content" in message:
                messages.append(
                    {"role": str(message["role"]), "content": str(message["content"])}
                )
        messages.append({"role": "user", "content": query})
        return messages

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
    def _assistant_tool_call_message(message: Any) -> Dict[str, Any]:
        """Re-serialize the assistant's tool-call message for the follow-up request."""
        return {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in message.tool_calls
            ],
        }

    async def stream(
        self, query: str, history: Optional[List[Dict[str, str]]] = None
    ) -> AsyncGenerator[str, None]:
        """
        Answer a query, letting the model call a registered tool first if it chooses to.

        Args:
            query: Current turn's user text.
            history: Prior conversation turns, most recent last.

        Yields:
            Text deltas, or a single ``[ERROR] ...`` string on failure.
        """
        try:
            standalone_query = self._query_rewriter.rewrite(query, history)
            messages = self._build_messages(standalone_query, history)
            tool_schemas = self._tool_registry.schemas()

            message = await self._client_provider.complete_with_tools_async(
                messages, tools=tool_schemas
            )

            if not message.tool_calls:
                yield message.content or ""
                return

            messages.append(self._assistant_tool_call_message(message))
            for tool_call in message.tool_calls:
                result = self._execute_tool_call(tool_call)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": result,
                    }
                )

            async for delta in self._client_provider.stream(messages):
                yield delta
        except Exception as exc:
            logger.exception("Tool-calling agent failed for query")
            yield f"[ERROR] {exc}"
