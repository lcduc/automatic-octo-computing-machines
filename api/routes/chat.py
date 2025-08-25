"""
Chat endpoint - RAG-powered conversation API with history support.
"""

# Standard library imports
import logging
import hashlib
import time

# Third-party imports
from fastapi import APIRouter, Query, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse

# Local imports
from api.dependencies import get_chat_service
from services import ChatService
from models.responses import ChatResponse, StatusEnum, ChatRequest
from config.llm.llm_config import LLMConfig

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/")
async def chat(
    request: ChatRequest, chat_service: ChatService = Depends(get_chat_service)
):
    """
    Chat endpoint for context-aware conversations with history support.
    Streams generated responses as tokens.
    """

    async def token_generator():
        async for token in chat_service.stream_chat_with_memory(request.query):
            yield token

    return StreamingResponse(token_generator(), media_type="text/event-stream")
