"""
Regression baselines for the eval scripts: committed numbers, the tolerance, and the pass/fail check.

``eval_router`` and ``eval_rag`` compare their report with ``demo_data/eval_baseline.json`` when run with
``--check`` (CI), and write it with ``--write-baseline``. The file only moves through an explicit
commit, so a regression cannot quietly become the new normal. Baselines have to be re-recorded when
the golden sets change: a different question set is not comparable.

Tolerances (starting points, not measured values):

- router: any real question stolen by a shortcut fails; accuracy may drop by at most 2 points or 2 messages,
  whichever is larger;
- retrieval: recall@k must not fall below the baseline; MRR may drop by at most 0.02.
"""

# Standard library imports
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

BASELINE_PATH = Path(__file__).parent / "demo_data" / "eval_baseline.json"
ROUTER_SECTION = "router"
ROUTER_MAX_ACCURACY_DROP = 0.02
ROUTER_MAX_MESSAGES_LOST = 2
MRR_MAX_DROP = 0.02
#: Float noise allowed when comparing rates that should be identical.
EPSILON = 1e-9


class EvalBaseline:
    """The committed baseline numbers and the check against a fresh report."""

    def __init__(self, path: Path = BASELINE_PATH):
        """
        Args:
            path: The baseline JSON file.
        """
        self._path = path

    def _read(self) -> Dict[str, Any]:
        """The file's content; empty when it does not exist yet."""
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def write(self, section: str, values: Dict[str, Any]) -> None:
        """Record ``values`` as the baseline of ``section`` (the caller commits the file)."""
        content = self._read()
        content[section] = values
        self._path.write_text(json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        logger.info("Baseline %r written to %s", section, self._path)

    def check_router(self, report: Dict[str, Any]) -> List[str]:
        """Problems of a router report against the baseline; empty when it holds."""
        stolen = report["questions_stolen_by_a_shortcut"]
        problems = [f"a real question was taken by a shortcut: {item['text']!r} -> {item['became']}" for item in stolen]
        baseline = self._read().get(ROUTER_SECTION)
        if baseline is None:
            return [*problems, "no router baseline recorded; run with --write-baseline and commit the file"]
        if baseline["cases"] != report["cases"]:
            return [*problems, f"the eval set changed ({baseline['cases']} -> {report['cases']} messages); re-record the baseline"]
        allowed_drop = max(ROUTER_MAX_ACCURACY_DROP, ROUTER_MAX_MESSAGES_LOST / report["cases"])
        if report["accuracy"] < baseline["accuracy"] - allowed_drop - EPSILON:
            problems.append(
                f"router accuracy {report['accuracy']:.1%} is below the baseline {baseline['accuracy']:.1%} "
                f"by more than {allowed_drop:.1%}"
            )
        return problems

    def check_retrieval(self, name: str, report: Dict[str, Any]) -> List[str]:
        """Problems of a retrieval report for golden set ``name`` against the baseline; empty when it holds."""
        baseline = self._read().get(name)
        if baseline is None:
            return [f"no retrieval baseline for {name!r}; run with --write-baseline and commit the file"]
        if baseline["answerable"] != report["answerable"]:
            return [f"{name}: the golden set changed ({baseline['answerable']} -> {report['answerable']} answerable); re-record the baseline"]
        problems = []
        if report["recall_at_k"] < baseline["recall_at_k"] - EPSILON:
            problems.append(f"{name}: recall@{report['top_k']} {report['recall_at_k']:.1%} fell below the baseline {baseline['recall_at_k']:.1%}")
        if report["mrr"] < baseline["mrr"] - MRR_MAX_DROP - EPSILON:
            problems.append(f"{name}: MRR {report['mrr']:.3f} dropped more than {MRR_MAX_DROP} below the baseline {baseline['mrr']:.3f}")
        return problems

    @staticmethod
    def router_values(report: Dict[str, Any]) -> Dict[str, Any]:
        """What a router baseline keeps of a report."""
        return {"cases": report["cases"], "accuracy": round(report["accuracy"], 4)}

    @staticmethod
    def retrieval_values(report: Dict[str, Any]) -> Dict[str, Any]:
        """What a retrieval baseline keeps of a report."""
        return {
            "answerable": report["answerable"],
            "recall_at_k": round(report["recall_at_k"], 4),
            "mrr": round(report["mrr"], 4),
        }
