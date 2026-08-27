"""
Simple prompt system - Universal prompt management for RAG chatbot.
Provides context-aware system prompts and custom prompt management.
"""

import logging

logger = logging.getLogger(__name__)


class SystemPrompts:
    """
    Universal prompt system that handles all conversation scenarios.
    Provides a single, comprehensive prompt template for consistent AI responses.
    """

    # Universal prompt template in Vietnamese.
    #
    # Deliberately free of any per-request substitution (no `{context}` or
    # similar): this string is sent byte-identical on every single request,
    # which is what makes it eligible for OpenAI's prompt caching (a stable,
    # >=1024-token prefix gets served from cache at a steep discount instead
    # of being reprocessed). Retrieved context is injected separately via
    # `PromptManager.build_context_block` and appended to the user turn
    # instead, so it never breaks this prefix.
    UNIVERSAL = """
    Bạn là trợ lý ảo của tôi — chatbot hỗ trợ đọc và phân tích dữ liệu từ các tài liệu.

    Nguyên tắc chính:
    - Luôn trả lời chỉ sử dụng ngữ cảnh đã được truy xuất được cung cấp trong prompt và lịch sử hội thoại. Hạn chế tối đa việc dựa vào kiến thức chung của chính bạn.
    - Không bịa đặt thông tin. Nếu câu trả lời không tìm thấy trong ngữ cảnh, hãy yêu cầu người dùng cung cấp thêm chi tiết. KHÔNG khẳng định những thông tin không có trong ngữ cảnh.
    - Không bao giờ đề cập đến ngữ cảnh hoặc cơ sở tri thức (knowledge base) trong câu trả lời.
    - Luôn cung cấp link/urls (nếu có).
    - Câu trả lời phải cùng ngôn ngữ với người dùng.

    Bạn sẽ nhận được ngữ cảnh liên quan (nếu có) ngay trong tin nhắn của người dùng, ngay trước câu hỏi. Hãy sử dụng ngữ cảnh đó để trả lời.
    """

    #: Shown to the user in place of retrieved context when the knowledge
    #: base has no documents yet.
    NO_CONTEXT_FALLBACK = (
        "Hiện chưa có tài liệu nào trong cơ sở tri thức. Người dùng cần tải lên tài liệu "
        "trước khi bạn có thể cung cấp câu trả lời dựa trên thông tin. Vui lòng hướng dẫn "
        "và khuyến khích họ tải lên tài liệu."
    )

    #: Wraps retrieved context so it reads clearly inside the user turn.
    CONTEXT_BLOCK = "Ngữ cảnh:\n{context}\n\nCâu hỏi: {query}"


class PromptManager:
    """
    Prompt management system for handling system prompts and custom prompt templates.
    Provides context-aware prompt generation and custom prompt support.
    """

    def __init__(self):
        # Store custom prompts for specialized use cases
        self.custom_prompts = {}

    def get_system_prompt(self, prompt_type: str = "universal", **kwargs) -> str:
        """
        Return the static system instructions for the AI conversation.

        The result is identical on every call for a given ``prompt_type``
        (no retrieved context or other per-request data is mixed in here),
        so it forms a stable prefix OpenAI's prompt caching can serve from
        cache at a discount instead of reprocessing. Use
        :meth:`build_context_block` to attach retrieved context to the user
        turn instead.

        Args:
            prompt_type: Type of prompt to use (defaults to universal)
            **kwargs: Formatting parameters for custom prompt templates

        Returns:
            The system prompt text ready for AI use
        """
        try:
            template = self.custom_prompts.get(prompt_type, SystemPrompts.UNIVERSAL)
            return template.format(**kwargs) if kwargs else template
        except Exception as e:
            logger.error(f"Error formatting prompt: {e}")
            return SystemPrompts.UNIVERSAL

    def build_context_block(self, query: str, context: str) -> str:
        """
        Format retrieved context and the user's question for the user turn.

        Kept out of the system message on purpose: the system message must
        stay byte-identical across requests to remain a cacheable prefix,
        so anything that varies per-request (retrieved context, the
        question itself) belongs in the user message instead.

        Args:
            query: The user's question.
            context: Retrieved RAG context, empty when none was found.

        Returns:
            Combined "context + question" text for the user message.
        """
        resolved_context = context if context and context.strip() else SystemPrompts.NO_CONTEXT_FALLBACK
        return SystemPrompts.CONTEXT_BLOCK.format(context=resolved_context, query=query)

    def add_custom_prompt(self, name: str, template: str):
        """Add custom prompt template for specialized use cases."""
        self.custom_prompts[name] = template
        logger.info(f"Added custom prompt: {name}")

    def list_available_prompts(self):
        """List all available prompts including custom ones."""
        return {
            "universal": "Universal prompt that handles all scenarios",
            **{name: "Custom prompt" for name in self.custom_prompts.keys()},
        }
