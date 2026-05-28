"""
Chat endpoint - RAG-powered conversation API with history support.
"""

# Standard library imports
import logging
import hashlib
import time

# Third-party imports
from fastapi import APIRouter, Query, HTTPException, Depends, Request, Body
from fastapi.responses import StreamingResponse
from typing import Union

# Local imports
from api.dependencies import get_chat_service
from services import ChatService
from models.responses import ChatResponse, StatusEnum, ChatRequest, QueryRequest
from config.settings import Config

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/")
async def chat(
    request: QueryRequest = Body(...), 
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    Chat endpoint with configurable mode (query-only or with history).
    Streams generated responses as tokens.
    """

    async def token_generator():
        # Extract query from request
        query = request.query
        if not query:
            yield "[ERROR] No query provided."
            return
        
        # Determine history based on configuration
        if Config.Chat.ENABLE_HISTORY():
            # History mode: no history for now (can be extended later)
            history = []
        else:
            # Query-only mode: no history
            history = None
        
        try:
            async for token in chat_service.stream_chat_with_memory(query, custom_history=history):
                yield token
        except Exception as e:
            # Catch any exceptions during streaming and yield error message
            logger.error(f"Error in token_generator: {e}", exc_info=True)
            yield f"[ERROR] {str(e)}"

    return StreamingResponse(token_generator(), media_type="text/event-stream")
