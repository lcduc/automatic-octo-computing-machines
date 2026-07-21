"""
Simple prompt system - Universal prompt management for RAG chatbot.
Provides context-aware system prompts and custom prompt management.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SystemPrompts:
    """
    Universal prompt system that handles all conversation scenarios.
    Provides a single, comprehensive prompt template for consistent AI responses.
    """

    DEFAULT_BOT_NAME = "Đa lĩnh vực"

    JOURNAL_BY_ID = {
        "CSCE": "Công nghệ thông tin - Truyền thông (JS:CSCE)",
        "EES": "Khoa học Trái đất và Môi trường (JS:EES)",
        "ER": "Nghiên cứu Giáo dục (JS:ER)",
        "LS": "Luật học (JS:LS)",
        "MAP": "Toán học - Vật lý (JS:MAP)",
        "MPS": "Khoa học Y Dược (JS:MPS)",
        "NST": "Khoa học Tự nhiên và Công nghệ (JS:NST)",
        "PAM": "Nghiên cứu Chính sách và Quản lý (JS:PAM)",
    }

    # Universal prompt template in Vietnamese
    UNIVERSAL = """
    Bạn là VNU JS Assistant — chatbot hỗ trợ học thuật cho Tạp chí Khoa học VNU: {bot_name}, Đại học Quốc gia Hà Nội.
    - Bạn đang phục vụ lĩnh vực: {journal_scope}
    - Khi người dùng đã chọn một mã tạp chí, CHỈ trả lời về chuyên san tương ứng với mã đó. Không thay bằng mô tả chung về toàn bộ hệ thống Tạp chí Khoa học ĐHQGHN; chỉ nêu thông tin chung khi nó trực tiếp làm rõ chuyên san đang chọn.
    Nguyên tắc chính:
    - Luôn trả lời chỉ sử dụng ngữ cảnh đã được truy xuất được cung cấp trong prompt và lịch sử hội thoại. Hạn chế tối đa việc dựa vào kiến thức chung của chính bạn.
    - Không bịa đặt thông tin. Nếu câu trả lời không tìm thấy trong ngữ cảnh, hãy yêu cầu người dùng cung cấp thêm chi tiết. KHÔNG khẳng định những thông tin không có trong ngữ cảnh.
    - Không bao giờ đề cập đến ngữ cảnh hoặc cơ sở tri thức (knowledge base) trong câu trả lời.
    - Luôn cung cấp link/urls (nếu có).
    - Câu trả lời phải cùng ngôn ngữ với người dùng.

    HƯỚNG DẪN ĐỊNH DẠNG:
    - Trả **CHỈ** HTML fragment (KHÔNG có <!DOCTYPE>, <html>, <head>, <body>). Không kèm giải thích, không kèm markdown/backticks, không kèm bình luận bên ngoài mã HTML.
    - Chỉ sử dụng các thẻ HTML đơn giản: div, h3, h4, ol, li, p, strong, em, a
    - Không sử dụng CSS nội tuyến hoặc thẻ <style>
    - Khi cần liên kết, sử dụng thẻ <a href="URL">Tên hiển thị</a>

    Ví dụ cấu trúc fragment:
    <div>
        <p>Nội dung mô tả...</p>
        
        <h4>Phần phụ</h4>
        <ol>
            <li>Mục đầu tiên</li>
            <li>Mục thứ hai</li>
        </ol>
        
        <div>
            <h4>Thông tin bổ sung</h4>
            <p>Chi tiết...</p>
        </div>
        
        <div>
            <p>[URL](URL)</p>
        </div>
    </div>
    
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

    def _resolve_journal_scope(self, dataset_id: Optional[str]) -> tuple[str, str]:
        """Resolve dataset id to journal scope label for prompt rendering."""
        if not dataset_id:
            return SystemPrompts.DEFAULT_BOT_NAME, "Tổng hợp đa lĩnh vực"

        normalized_id = dataset_id.strip().upper()
        resolved_scope = SystemPrompts.JOURNAL_BY_ID.get(normalized_id)
        if not resolved_scope:
            return SystemPrompts.DEFAULT_BOT_NAME, f"Mã lĩnh vực {normalized_id}"

        return resolved_scope, resolved_scope

    def get_system_prompt(
        self,
        prompt_type: str = "universal",
        context: str = "",
        dataset_id: Optional[str] = None,
        **kwargs,
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

            resolved_bot_name, resolved_journal_scope = self._resolve_journal_scope(dataset_id)
            return template.format(
                context=context,
                bot_name=kwargs.get("bot_name", resolved_bot_name),
                journal_scope=kwargs.get("journal_scope", resolved_journal_scope),
                **kwargs,
            )

        except Exception as e:
            logger.error(f"Error formatting prompt: {e}")
            # Fallback to safe context handling
            safe_context = context if context else "No context available."
            resolved_bot_name, resolved_journal_scope = self._resolve_journal_scope(dataset_id)
            return SystemPrompts.UNIVERSAL.format(
                context=safe_context,
                bot_name=resolved_bot_name,
                journal_scope=resolved_journal_scope,
            )

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
