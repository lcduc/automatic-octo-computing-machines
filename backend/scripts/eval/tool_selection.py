"""
Tool selection and argument accuracy (EVAL-05) against the demo shop's tools (TOOL-11).

Each labelled question goes through what a chat turn does before a tool runs: the LLM
``IntentRouter`` (rag / action / login), then, for an action, the ``ToolCallingAgent``'s
decision call with the tools the caller's tier is offered. The tools are the built-in
``get_current_time`` plus ``deploy/business_db/demo_tools.json``, compiled by the same
``SqlToolCatalog`` code a deployment uses; nothing is executed, so no database is needed.

Scored:
* **Selection**: the first tool called, or ``login_required`` / ``no_tool``, against ``expected``.
* **Arguments** (correct selections with ``expected_arguments``): the model's arguments and the
  expected ones are both parsed by the tool's real ``ToolArguments`` into SQL parameters, so
  "tháng trước" and "last month" count as the same period. A list is a set of accepted values.

Calls the LLM (two to three calls per question). Exits 1 when any call failed, since a failed
intent call silently routes to rag and would score as a correct ``no_tool``.

Usage (from ``backend/``):
    python -m scripts.eval.tool_selection
    python -m scripts.eval.tool_selection --out logs/tool_selection.json
"""

# Standard library imports
import argparse
import asyncio
import itertools
import json
import logging
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# Local imports
from app.config.settings import Config
from app.core.agent.intent_router import IntentRouter
from app.core.agent.openai_client import OpenAIClientProvider
from app.core.agent.provider_factory import LLMProviderFactory
from app.core.agent.query_rewriter import QueryRewriter
from app.core.agent.tool_calling_agent import ToolCallingAgent
from app.core.agent.tools.current_time_tool import CurrentTimeTool
from app.core.agent.tools.registry import ToolRegistry
from app.core.agent.tools.sql_tool_executor import SqlToolExecutor
from app.core.agent.tools.tool_arguments import ToolArguments, ToolArgumentsError
from app.models.intent import IntentType
from app.models.tool_context import ToolContext
from app.services.host_identity_service import HostIdentityService
from app.services.sql_tool_catalog import SqlToolCatalog

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CASES_PATH = BACKEND_DIR / "scripts" / "demo_data" / "golden_tool_calls.json"
DEFAULT_TOOLS_PATH = BACKEND_DIR.parent / "deploy" / "business_db" / "demo_tools.json"

NO_TOOL = "no_tool"
LOGIN_REQUIRED = "login_required"
CALLER_ANONYMOUS = "anonymous"
#: Tier of a signed-in eval caller (the lowest logged-in tier of the default ``HOST_TIERS``).
CALLER_USER = "user"
EVAL_USER_ID = "eval-user"
#: A caller every tool permits, to read every tool's schema.
EVERY_TIER = ToolContext(tier_level=sys.maxsize)


@dataclass(frozen=True)
class ToolCase:
    """One labelled question."""

    query: str
    caller: str
    lang: str
    expected: str
    expected_arguments: Optional[Dict[str, Any]] = None


def load_cases(path: Path) -> List[ToolCase]:
    """The labelled questions in ``path``."""
    with open(path, encoding="utf-8") as handle:
        return [ToolCase(**item) for item in json.load(handle)]


def demo_registry(tools_path: Path) -> ToolRegistry:
    """The registry a deployment with the demo shop's tools would have (no database needed)."""
    with open(tools_path, encoding="utf-8") as handle:
        definitions = json.load(handle)
    # The executor is never used: tools are compiled to read their schemas, never run.
    catalog = SqlToolCatalog(None, SqlToolExecutor(None, 0), HostIdentityService.from_config(None).tier_level)
    return ToolRegistry(tools=[CurrentTimeTool(), *catalog.compile_definitions(definitions)])


def caller_context(caller: str) -> ToolContext:
    """The verified caller a case's ``caller`` stands for."""
    if caller == CALLER_ANONYMOUS:
        return ToolContext()
    return ToolContext(user_id=EVAL_USER_ID, tier_level=HostIdentityService.from_config(None).tier_level(caller))


def _normalized(value: Any) -> Any:
    """Strings compared case-, space- and Unicode-form-insensitively."""
    return unicodedata.normalize("NFC", value).strip().casefold() if isinstance(value, str) else value


def sql_parameters(schema: Dict[str, Any], arguments: Dict[str, Any], today: date) -> Dict[str, Any]:
    """
    The SQL parameters ``arguments`` become, as the tool would bind them.

    Raises:
        ToolArgumentsError: The tool would refuse these arguments.
    """
    parsed = ToolArguments(schema).parse(arguments, lambda: today)
    return {name: _normalized(value) for name, value in parsed.items()}


def accepted_arguments(expected: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every argument set ``expected`` accepts (a list value means any one of its items)."""
    names = sorted(expected)
    options = [expected[name] if isinstance(expected[name], list) else [expected[name]] for name in names]
    return [dict(zip(names, combination)) for combination in itertools.product(*options)]


def arguments_match(schema: Dict[str, Any], actual: Dict[str, Any], expected: Dict[str, Any], today: date) -> bool:
    """
    Whether ``actual`` binds the same SQL parameters as one accepted set in ``expected``.

    An optional argument the model added unasked (e.g. a status filter) is a mismatch.

    Raises:
        ToolArgumentsError: The tool would refuse ``actual``.
    """
    got = sql_parameters(schema, actual, today)
    return any(sql_parameters(schema, candidate, today) == got for candidate in accepted_arguments(expected))


class ToolSelectionEvaluator:
    """Runs labelled questions through the intent router and the tool agent's decision call."""

    def __init__(self, intent_router: IntentRouter, agent: ToolCallingAgent, registry: ToolRegistry, today: date):
        """
        Args:
            intent_router: Router in front of the agent, as in a chat turn.
            agent: Tool agent whose decision call is scored.
            registry: The agent's tools (to read schemas and what each caller is offered).
            today: Date periods like "tháng trước" are resolved against.
        """
        self._intent_router = intent_router
        self._agent = agent
        self._registry = registry
        self._today = today
        self._tools = {schema["function"]["name"]: schema["function"]["parameters"]
                       for schema in registry.schemas(EVERY_TIER)}

    async def evaluate_one(self, case: ToolCase) -> Dict[str, Any]:
        """Score one question (two to three LLM calls)."""
        context = caller_context(case.caller)
        record: Dict[str, Any] = {"query": case.query, "caller": case.caller, "lang": case.lang,
                                  "expected": case.expected, "tools_called": [], "arguments": None,
                                  "arguments_correct": None, "arguments_invalid": False}
        intent, usage = await self._intent_router.classify(case.query, None, None, context)
        record["route"] = intent.value
        # The router answers rag without usage when its call failed.
        record["llm_failed"] = usage is None
        if intent == IntentType.LOGIN_REQUIRED:
            record["predicted"] = LOGIN_REQUIRED
        elif intent == IntentType.ACTION:
            try:
                _, message, _ = await self._agent.decide(case.query, context=context)
            except Exception:
                logger.exception("Decision call failed for %r", case.query)
                record["llm_failed"] = True
                message = None
            calls = list(getattr(message, "tool_calls", None) or [])
            record["tools_called"] = [call.function.name for call in calls]
            record["predicted"] = calls[0].function.name if calls else NO_TOOL
            if calls:
                record["arguments"] = calls[0].function.arguments
        else:
            record["predicted"] = NO_TOOL
        offered = {schema["function"]["name"] for schema in self._registry.schemas(context)}
        record["unoffered_tool_called"] = any(name not in offered for name in record["tools_called"])
        record["correct"] = record["predicted"] == case.expected
        if record["correct"] and case.expected_arguments is not None and case.expected in self._tools:
            self._score_arguments(record, self._tools[case.expected], case.expected_arguments)
        return record

    def _score_arguments(self, record: Dict[str, Any], schema: Dict[str, Any], expected: Dict[str, Any]) -> None:
        """Fill ``arguments_correct`` / ``arguments_invalid`` for a correctly selected tool."""
        try:
            actual = json.loads(record["arguments"] or "{}")
            if not isinstance(actual, dict):
                raise ToolArgumentsError("arguments are not a JSON object")
            record["arguments_correct"] = arguments_match(schema, actual, expected, self._today)
        except (ValueError, ToolArgumentsError):
            # ToolArgumentsError is a ValueError too: malformed JSON or arguments the tool refuses.
            record["arguments_correct"] = False
            record["arguments_invalid"] = True

    async def evaluate_all(self, cases: List[ToolCase]) -> List[Dict[str, Any]]:
        """Score every case, one at a time (a small, infrequent run; no rate-limit bursts)."""
        return [await self.evaluate_one(case) for case in cases]


def _accuracy(records: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    """Correct / total of ``records`` for a boolean ``key``."""
    correct = sum(1 for record in records if record[key])
    return {"total": len(records), "correct": correct, "accuracy": correct / len(records) if records else 0.0}


def build_report(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Selection and argument accuracy overall, per expected label, language and caller."""
    groups: Dict[str, Dict[str, List[Dict[str, Any]]]] = {"by_expected": defaultdict(list),
                                                           "by_lang": defaultdict(list),
                                                           "by_caller": defaultdict(list)}
    for record in records:
        groups["by_expected"][record["expected"]].append(record)
        groups["by_lang"][record["lang"]].append(record)
        groups["by_caller"][record["caller"]].append(record)
    scored_arguments = [record for record in records if record["arguments_correct"] is not None]
    return {
        "selection": _accuracy(records, "correct"),
        **{name: {label: _accuracy(members, "correct") for label, members in sorted(group.items())}
           for name, group in groups.items()},
        "confusion": dict(Counter(f"{record['expected']} -> {record['predicted']}" for record in records)),
        "arguments": {**_accuracy(scored_arguments, "arguments_correct"),
                      "invalid": sum(1 for record in scored_arguments if record["arguments_invalid"])},
        "llm_failures": sum(1 for record in records if record["llm_failed"]),
        "unoffered_tool_calls": sum(1 for record in records if record["unoffered_tool_called"]),
        "selection_misses": [record for record in records if not record["correct"]],
        "argument_misses": [record for record in scored_arguments if not record["arguments_correct"]],
        "per_query": records,
    }


def print_report(report: Dict[str, Any]) -> None:
    """Human-readable summary."""
    selection, arguments = report["selection"], report["arguments"]
    print(f"\nTool selection eval: {selection['total']} questions")
    print(f"  Selection accuracy: {selection['correct']}/{selection['total']} ({selection['accuracy']:.1%})")
    print(f"  Argument accuracy:  {arguments['correct']}/{arguments['total']} ({arguments['accuracy']:.1%}),"
          f" {arguments['invalid']} refused by the tool")
    if report["llm_failures"]:
        print(f"  WARNING: {report['llm_failures']} LLM calls failed; check the provider key and the logs. "
              "The numbers above are not trustworthy.")
    if report["unoffered_tool_calls"]:
        print(f"  {report['unoffered_tool_calls']} calls named a tool the caller is not offered (refused at execution).")
    for name in ("by_expected", "by_lang", "by_caller"):
        print(f"\n  {name.replace('_', ' ')}:")
        for label, stats in report[name].items():
            print(f"    {label:18s} {stats['correct']}/{stats['total']}  ({stats['accuracy']:.0%})")
    print("\n  Expected -> predicted:")
    for pair, count in sorted(report["confusion"].items()):
        print(f"    {count:3d}  {pair}")
    for miss in report["selection_misses"]:
        print(f"  SELECTION MISS [{miss['caller']}] expected={miss['expected']} got={miss['predicted']}"
              f" (route {miss['route']}): {miss['query']}")
    for miss in report["argument_misses"]:
        print(f"  ARGUMENT MISS {miss['expected']} {miss['arguments']}: {miss['query']}")
    print()


async def run(cases_path: Path, tools_path: Path) -> Dict[str, Any]:
    """Build the pipeline pieces as ``AppContainer`` does and score every case."""
    registry = demo_registry(tools_path)
    llm = LLMProviderFactory.create()
    intent_router = IntentRouter(llm, registry, login_available=True)
    agent = ToolCallingAgent(OpenAIClientProvider(), registry, QueryRewriter(llm))
    today = datetime.now(ZoneInfo(Config.Server.APP_TIMEZONE())).date()
    evaluator = ToolSelectionEvaluator(intent_router, agent, registry, today)
    return build_report(await evaluator.evaluate_all(load_cases(cases_path)))


def main() -> int:
    """Run the eval, print and optionally save the report; returns the exit code."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH, help="Labelled questions (JSON)")
    parser.add_argument("--tools", type=Path, default=DEFAULT_TOOLS_PATH, help="SQL tool definitions (JSON)")
    parser.add_argument("--out", type=Path, default=None, help="Optional path for the full JSON report")
    args = parser.parse_args()

    report = asyncio.run(run(args.cases, args.tools))
    print_report(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"Full report saved to {args.out}")
    return 1 if report["llm_failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
