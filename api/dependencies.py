"""
FastAPI dependencies for dependency injection and service management.
Provides service instances for API endpoints with proper dependency injection.
"""

# Local imports
from services import DocumentService, ChatService, UploadService, URLService
from core.llm import ChatbotService
from core.rag import ContextRetriever


def get_document_service() -> DocumentService:
    """Get document service instance for document processing and management."""
    # You can inject custom processors or file managers here if needed
    return DocumentService()


def get_chat_service() -> ChatService:
    """Get chat service instance for RAG-powered conversation handling."""
    # Wire up dependencies explicitly
    context_retriever = ContextRetriever()
    chatbot_service = ChatbotService(context_retriever=context_retriever)
    return ChatService(chatbot_service=chatbot_service)


def get_upload_service() -> UploadService:
    """Get upload service instance for file upload and processing."""
    return UploadService()


def get_url_service() -> URLService:
    """Get URL service instance for web content extraction and processing."""
    return URLService()
