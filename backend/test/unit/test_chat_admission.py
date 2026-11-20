"""Unit tests for ChatService's admission: a generation slot taken in ``prepare`` and held for the turn."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.chat_service import ChatService, PreparedTurn
from app.services.errors import ServiceUnavailableError
from app.services.usage_service import BudgetVerdict

SLOT_COUNT = 2
SHORT_WAIT_SECONDS = 0.05
LONG_WAIT_SECONDS = 1.0
RELEASE_AFTER_SECONDS = 0.02
WAITING_REQUESTS = 5


def _service(monkeypatch, wait_seconds: float) -> ChatService:
    monkeypatch.setenv("MAX_CONCURRENT_CHATS", str(SLOT_COUNT))
    monkeypatch.setenv("CHAT_ADMISSION_WAIT_SECONDS", str(wait_seconds))
    return ChatService(None, None, None, None, None, None, None, None)


def _held_turn() -> PreparedTurn:
    return PreparedTurn(None, uuid.uuid4(), uuid.uuid4(), None, 0.0, holds_slot=True)


async def _fill_slots(service: ChatService) -> None:
    for _ in range(SLOT_COUNT):
        await service._take_slot()


async def _admitted(service: ChatService) -> bool:
    try:
        await service._take_slot()
    except ServiceUnavailableError:
        return False
    return True


@pytest.mark.asyncio
async def test_free_slot_is_taken_and_held_until_released_once(monkeypatch):
    service = _service(monkeypatch, SHORT_WAIT_SECONDS)
    await _fill_slots(service)
    assert service._slots.locked()  # taken slots stay taken
    turn = _held_turn()
    service.release_slot(turn)
    service.release_slot(turn)  # a second release must not free a slot it does not hold
    await service._take_slot()
    assert not await _admitted(service)


@pytest.mark.asyncio
async def test_request_gets_a_slot_that_frees_within_the_wait(monkeypatch):
    service = _service(monkeypatch, LONG_WAIT_SECONDS)
    await _fill_slots(service)
    asyncio.get_running_loop().call_later(RELEASE_AFTER_SECONDS, service._slots.release)
    await service._take_slot()


@pytest.mark.asyncio
async def test_request_is_refused_when_no_slot_frees_in_time(monkeypatch):
    service = _service(monkeypatch, SHORT_WAIT_SECONDS)
    await _fill_slots(service)
    with pytest.raises(ServiceUnavailableError):
        await service._take_slot()
    service._slots.release()
    assert await _admitted(service)  # the refused request left no slot behind


@pytest.mark.asyncio
async def test_one_freed_slot_admits_one_waiting_request_not_all(monkeypatch):
    """Regression: checking a slot and giving it back let every waiter in when one turn ended."""
    service = _service(monkeypatch, LONG_WAIT_SECONDS)
    await _fill_slots(service)
    waiters = [asyncio.create_task(_admitted(service)) for _ in range(WAITING_REQUESTS)]
    await asyncio.sleep(RELEASE_AFTER_SECONDS)
    service._slots.release()
    await asyncio.sleep(RELEASE_AFTER_SECONDS)
    assert sum(waiter.done() and waiter.result() for waiter in waiters) == 1
    for waiter in waiters:
        waiter.cancel()


@pytest.mark.asyncio
async def test_zero_wait_admits_when_a_slot_is_free(monkeypatch):
    """Regression: wait_for(..., 0) on Python 3.11 refused even when every slot was free."""
    service = _service(monkeypatch, 0.0)
    await service._take_slot()


@pytest.mark.asyncio
async def test_zero_wait_refuses_at_once_when_every_slot_is_busy(monkeypatch):
    service = _service(monkeypatch, 0.0)
    await _fill_slots(service)
    assert not await _admitted(service)


@pytest.mark.asyncio
async def test_prepare_gives_the_slot_back_when_opening_the_turn_fails(monkeypatch):
    service = _service(monkeypatch, SHORT_WAIT_SECONDS)
    service._settings = SimpleNamespace(usage_policy=lambda: None)
    service._usage = SimpleNamespace(
        hit_request_limits=AsyncMock(return_value=None),
        budget_verdict=AsyncMock(return_value=BudgetVerdict.OK),
    )
    monkeypatch.setattr(service, "_open_turn", AsyncMock(side_effect=RuntimeError("database down")))
    caller = SimpleNamespace(logged_in=False)
    with pytest.raises(RuntimeError):
        await service.prepare(caller, "xin chào", None, None)
    await _fill_slots(service)  # every slot is still free
