"""EVAL-05 scoring (``scripts/eval/tool_selection.py``) without an LLM: labels, argument matching, routing outcomes."""

import types
from datetime import date

import pytest

from app.core.agent.tools.tool_arguments import ToolArgumentsError
from app.models.intent import IntentType
from app.models.llm import LLMUsage
from scripts.eval.tool_selection import (
    DEFAULT_CASES_PATH,
    DEFAULT_TOOLS_PATH,
    EVERY_TIER,
    LOGIN_REQUIRED,
    NO_TOOL,
    ToolCase,
    ToolSelectionEvaluator,
    accepted_arguments,
    arguments_match,
    build_report,
    caller_context,
    demo_registry,
    load_cases,
    sql_parameters,
)

TODAY = date(2026, 11, 11)
USAGE = LLMUsage("openai", "test-model")


@pytest.fixture(scope="module")
def registry():
    return demo_registry(DEFAULT_TOOLS_PATH)


@pytest.fixture(scope="module")
def schemas(registry):
    return {schema["function"]["name"]: schema["function"]["parameters"] for schema in registry.schemas(EVERY_TIER)}


def test_every_label_names_a_real_tool_and_parses(schemas):
    """A typo in the labelled set would otherwise only show up as a model 'miss'."""
    cases = load_cases(DEFAULT_CASES_PATH)
    assert cases
    for case in cases:
        assert case.expected in {*schemas, NO_TOOL, LOGIN_REQUIRED}, case.query
        caller_context(case.caller)
        if case.expected_arguments is not None:
            for candidate in accepted_arguments(case.expected_arguments):
                sql_parameters(schemas[case.expected], candidate, TODAY)


def test_login_required_cases_are_anonymous_and_ask_for_a_private_tool(registry):
    for case in load_cases(DEFAULT_CASES_PATH):
        if case.expected == LOGIN_REQUIRED:
            assert case.caller == "anonymous", case.query
        elif case.expected not in (NO_TOOL,):
            offered = {schema["function"]["name"] for schema in registry.schemas(caller_context(case.caller))}
            assert case.expected in offered, case.query


def test_periods_match_across_phrasing_and_language(schemas):
    orders = schemas["list_my_orders"]
    assert arguments_match(orders, {"period": "last month"}, {"period": "tháng trước"}, TODAY)
    assert arguments_match(orders, {"period": "2026-10-01..2026-10-31"}, {"period": "tháng trước"}, TODAY)
    assert not arguments_match(orders, {"period": "tháng này"}, {"period": "tháng trước"}, TODAY)


def test_an_unrequested_filter_is_a_mismatch(schemas):
    orders = schemas["list_my_orders"]
    assert not arguments_match(orders, {"period": "tháng trước", "status": "paid"}, {"period": "tháng trước"}, TODAY)


def test_strings_ignore_case_and_any_accepted_value_matches(schemas):
    price = schemas["get_product_price"]
    assert arguments_match(price, {"query": "Áo Thun "}, {"query": ["áo thun cotton", "áo thun"]}, TODAY)
    assert not arguments_match(price, {"query": "ao thun"}, {"query": "áo thun"}, TODAY)


def test_arguments_the_tool_refuses_raise(schemas):
    with pytest.raises(ToolArgumentsError):
        arguments_match(schemas["list_my_orders"], {"period": "hồi đó"}, {"period": "tháng trước"}, TODAY)


class _Router:
    def __init__(self, intent, usage=USAGE):
        self._result = (intent, usage)

    async def classify(self, query, history=None, model=None, context=None):
        return self._result


class _Agent:
    def __init__(self, calls):
        self._calls = calls

    async def decide(self, query, history=None, model=None, light_model=None, context=None):
        tool_calls = [types.SimpleNamespace(function=types.SimpleNamespace(name=name, arguments=arguments))
                      for name, arguments in self._calls]
        return [], types.SimpleNamespace(content=None, tool_calls=tool_calls), [USAGE]


ORDERS_CASE = ToolCase("Tháng trước mình đặt những đơn nào?", "user", "vi", "list_my_orders", {"period": "tháng trước"})


async def _score(registry, router, agent, case=ORDERS_CASE):
    return await ToolSelectionEvaluator(router, agent, registry, TODAY).evaluate_one(case)


@pytest.mark.asyncio
async def test_right_tool_with_equivalent_arguments_scores_both(registry):
    record = await _score(registry, _Router(IntentType.ACTION), _Agent([("list_my_orders", '{"period": "last month"}')]))

    assert record["correct"] and record["arguments_correct"] and not record["llm_failed"]


@pytest.mark.asyncio
async def test_malformed_arguments_count_as_refused(registry):
    record = await _score(registry, _Router(IntentType.ACTION), _Agent([("list_my_orders", "{not json")]))

    assert record["correct"] and record["arguments_correct"] is False and record["arguments_invalid"]


@pytest.mark.asyncio
async def test_rag_route_is_no_tool_and_a_failed_router_call_is_flagged(registry):
    record = await _score(registry, _Router(IntentType.RAG, usage=None), _Agent([]))

    assert record["predicted"] == NO_TOOL and not record["correct"] and record["llm_failed"]


@pytest.mark.asyncio
async def test_anonymous_naming_a_private_tool_is_reported(registry):
    case = ToolCase("Đơn của tôi?", "anonymous", "vi", LOGIN_REQUIRED)
    record = await _score(registry, _Router(IntentType.ACTION), _Agent([("list_my_orders", '{"period": "tháng này"}')]), case)

    assert record["unoffered_tool_called"] and record["predicted"] == "list_my_orders" and not record["correct"]


@pytest.mark.asyncio
async def test_report_separates_selection_from_arguments(registry):
    records = [
        await _score(registry, _Router(IntentType.ACTION), _Agent([("list_my_orders", '{"period": "tháng trước"}')])),
        await _score(registry, _Router(IntentType.ACTION), _Agent([("list_my_orders", '{"period": "tháng này"}')])),
        await _score(registry, _Router(IntentType.LOGIN_REQUIRED), _Agent([])),
    ]

    report = build_report(records)

    assert report["selection"] == {"total": 3, "correct": 2, "accuracy": pytest.approx(2 / 3)}
    assert report["arguments"]["total"] == 2 and report["arguments"]["correct"] == 1
    assert report["confusion"] == {"list_my_orders -> list_my_orders": 2, "list_my_orders -> login_required": 1}
    assert report["llm_failures"] == 0
