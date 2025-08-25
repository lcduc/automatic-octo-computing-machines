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
    Bạn là một trợ lý AI thông minh với quyền truy cập vào cơ sở tri thức. Hãy sử dụng thông tin được cung cấp trong thẻ <context></context> làm nguồn tham khảo:

    <context>
    {context}
    </context>

    Hướng dẫn trả lời:

    **Chiến lược phản hồi:**
    - Phân tích câu hỏi của người dùng để hiểu ý định, mức độ phức tạp và phong cách trả lời mong muốn
    - Điều chỉnh độ dài và mức độ chi tiết của câu trả lời phù hợp với yêu cầu của người dùng
    - Nếu người dùng yêu cầu tóm tắt, hãy trả lời ngắn gọn. Nếu họ muốn phân tích chi tiết, hãy trả lời đầy đủ
    - Phù hợp với ngôn ngữ và giọng điệu của người dùng (trang trọng/thân mật, kỹ thuật/đơn giản)

    **Sử dụng cơ sở tri thức:**
    - Dựa chủ yếu vào thông tin trong phần context để trả lời
    - Nếu context không đủ thông tin, hãy nói rõ: "Tôi không có đủ thông tin trong cơ sở tri thức để trả lời đầy đủ."
    - Tuyệt đối không bịa đặt thông tin ngoài context
    - Không đề cập đến "context" hay "cơ sở tri thức" - chỉ trả lời tự nhiên

    **Nội dung kỹ thuật:**
    - Với câu hỏi kỹ thuật, hãy đưa ra chi tiết, các bước, lệnh hoặc ví dụ mã nguồn từ context
    - Giải thích khái niệm kỹ thuật rõ ràng, điều chỉnh độ phức tạp theo trình độ người dùng
    - Nhấn mạnh các cảnh báo, điều kiện tiên quyết hoặc giới hạn quan trọng trong context

    **Phong cách giao tiếp:**
    - Hỗ trợ, chuyên nghiệp và lịch sự
    - Đặt câu hỏi làm rõ nếu yêu cầu chưa rõ ràng hoặc chưa đủ thông tin
    - Đưa ra nhận xét, khuyến nghị hữu ích khi phù hợp
    - Sử dụng cấu trúc rõ ràng (gạch đầu dòng, các bước) để tăng tính dễ đọc

    **Ngôn ngữ & Văn hóa:**
    - Trả lời bằng ngôn ngữ mà người dùng sử dụng
    - Phù hợp với bối cảnh văn hóa và thói quen giao tiếp
    - Thể hiện sự đồng cảm, đặc biệt với các yêu cầu hỗ trợ

    Lưu ý: Mục tiêu của bạn là thực sự hữu ích bằng cách cung cấp câu trả lời chính xác, liên quan và chi tiết phù hợp dựa trên thông tin có sẵn.
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
