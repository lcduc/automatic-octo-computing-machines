"""Unit tests for ChatService's bounded wait for a free generation slot."""

import asyncio

import pytest

from app.services.chat_service import ChatService
from app.services.errors import ServiceUnavailableError

SLOT_COUNT = 2
SHORT_WAIT_SECONDS = 0.05
LONG_WAIT_SECONDS = 1.0
RELEASE_AFTER_SECONDS = 0.02


def _service(monkeypatch, wait_seconds: float) -> ChatService:
    monkeypatch.setenv("MAX_CONCURRENT_CHATS", str(SLOT_COUNT))
    monkeypatch.setenv("CHAT_ADMISSION_WAIT_SECONDS", str(wait_seconds))
    return ChatService(None, None, None, None, None, None, None, None)


async def _fill_slots(service: ChatService) -> None:
    for _ in range(SLOT_COUNT):
        await service._slots.acquire()


@pytest.mark.asyncio
async def test_free_slot_is_admitted_at_once_and_not_held(monkeypatch):
    service = _service(monkeypatch, SHORT_WAIT_SECONDS)
    await service._wait_for_free_slot()
    assert not service._slots.locked()
    await _fill_slots(service)  # both slots still available afterwards


@pytest.mark.asyncio
async def test_request_gets_a_slot_that_frees_within_the_wait(monkeypatch):
    service = _service(monkeypatch, LONG_WAIT_SECONDS)
    await _fill_slots(service)
    asyncio.get_running_loop().call_later(RELEASE_AFTER_SECONDS, service._slots.release)
    await service._wait_for_free_slot()


@pytest.mark.asyncio
async def test_request_is_refused_when_no_slot_frees_in_time(monkeypatch):
    service = _service(monkeypatch, SHORT_WAIT_SECONDS)
    await _fill_slots(service)
    with pytest.raises(ServiceUnavailableError):
        await service._wait_for_free_slot()
    assert service._slots.locked()  # the refused request left no slot behind
