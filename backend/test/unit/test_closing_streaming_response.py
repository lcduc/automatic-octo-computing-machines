"""Unit tests for ClosingStreamingResponse: ``on_close`` runs even when the body never starts."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import ClientDisconnect

from app.api.closing_streaming_response import ClosingStreamingResponse

#: ASGI spec versions: before 2.4 Starlette watches for the disconnect, from 2.4 it relies on send raising OSError.
LEGACY_SPEC = {"type": "http", "asgi": {"spec_version": "2.3"}}
CURRENT_SPEC = {"type": "http", "asgi": {"spec_version": "2.4"}}
STALL_SECONDS = 5.0


class _Body:
    """Body iterator that records whether Starlette ever started it."""

    def __init__(self) -> None:
        self.started = False

    async def events(self):
        self.started = True
        yield "data: hello\n\n"


async def _client_gone() -> dict:
    return {"type": "http.disconnect"}


async def _stalled_send(message: dict) -> None:
    """A send still writing the headers when Starlette sees the disconnect and cancels it."""
    await asyncio.sleep(STALL_SECONDS)


@pytest.mark.asyncio
async def test_on_close_runs_after_a_finished_stream():
    body, on_close = _Body(), Mock()
    response = ClosingStreamingResponse(body.events(), on_close=on_close)
    await response(CURRENT_SPEC, _client_gone, AsyncMock())
    assert body.started
    on_close.assert_called_once()


@pytest.mark.asyncio
async def test_on_close_runs_when_the_client_left_before_the_body_started():
    body, on_close = _Body(), Mock()
    response = ClosingStreamingResponse(body.events(), on_close=on_close)
    await response(LEGACY_SPEC, _client_gone, _stalled_send)
    assert not body.started
    on_close.assert_called_once()


@pytest.mark.asyncio
async def test_on_close_runs_when_sending_the_headers_fails():
    body, on_close = _Body(), Mock()
    response = ClosingStreamingResponse(body.events(), on_close=on_close)
    with pytest.raises(ClientDisconnect):
        await response(CURRENT_SPEC, _client_gone, AsyncMock(side_effect=OSError("client gone")))
    assert not body.started
    on_close.assert_called_once()
