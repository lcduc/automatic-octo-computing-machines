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

    # Universal prompt template in Vietnamese
    UNIVERSAL = """
    Bạn là trợ lý ảo của tôi — chatbot hỗ trợ đọc và phân tích dữ liệu từ các tài liệu.

    Nguyên tắc chính:
    - Luôn trả lời chỉ sử dụng ngữ cảnh đã được truy xuất được cung cấp trong prompt và lịch sử hội thoại. Hạn chế tối đa việc dựa vào kiến thức chung của chính bạn.
    - Không bịa đặt thông tin. Nếu câu trả lời không tìm thấy trong ngữ cảnh, hãy yêu cầu người dùng cung cấp thêm chi tiết. KHÔNG khẳng định những thông tin không có trong ngữ cảnh.
    - Không bao giờ đề cập đến ngữ cảnh hoặc cơ sở tri thức (knowledge base) trong câu trả lời.
    - Luôn cung cấp link/urls (nếu có).
    - Câu trả lời phải cùng ngôn ngữ với người dùng.

    HƯỚNG DẪN ĐỊNH DẠNG:
    - Trả lời bằng Markdown chuẩn. KHÔNG dùng HTML, KHÔNG bọc toàn bộ câu trả lời trong backticks.
    - Dùng ## hoặc ### cho tiêu đề, **chữ đậm** để nhấn mạnh, "- " hoặc "1. " cho danh sách.
    - Khi cần liên kết, dùng cú pháp [Tên hiển thị](URL).
    - Không kèm giải thích về cách định dạng, chỉ trả lời trực tiếp bằng nội dung.

    Ví dụ cấu trúc câu trả lời:
    ## Tiêu đề chính

    Nội dung mô tả...

    ### Phần phụ
    1. Mục đầu tiên
    2. Mục thứ hai

    **Thông tin bổ sung:** chi tiết...

    [Tên liên kết](URL)

    Hãy trả lời ngay bây giờ bằng cách sử dụng ngữ cảnh sau: {context}
    """


class PromptManager:
    """
    Prompt management system for handling system prompts and custom prompt templates.
    Provides context-aware prompt generation and custom prompt support.
    """

    def __init__(self):
        # Store custom prompts for specialized use cases
        self.custom_prompts = {}

    def get_system_prompt(
        self, prompt_type: str = "universal", context: str = "", **kwargs
    ) -> str:
        """
        Generate system prompt with context for AI conversation.

        Args:
            prompt_type: Type of prompt to use (defaults to universal)
            context: Document context for RAG responses
            **kwargs: Additional formatting parameters

        Returns:
            Formatted system prompt ready for AI use
        """
        try:
            # Use custom prompt if available, otherwise fall back to universal
            if prompt_type in self.custom_prompts:
                template = self.custom_prompts[prompt_type]
            else:
                # Use universal prompt for all scenarios
                template = SystemPrompts.UNIVERSAL

            # Handle empty context gracefully with helpful guidance
            if not context or not context.strip():
                context = "Hiện chưa có tài liệu nào trong cơ sở tri thức. Người dùng cần tải lên tài liệu trước khi bạn có thể cung cấp câu trả lời dựa trên thông tin. Vui lòng hướng dẫn và khuyến khích họ tải lên tài liệu."

            return template.format(context=context, **kwargs)

        except Exception as e:
            logger.error(f"Error formatting prompt: {e}")
            # Fallback to safe context handling
            safe_context = context if context else "No context available."
            return SystemPrompts.UNIVERSAL.format(context=safe_context)

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
