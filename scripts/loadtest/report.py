"""
Turn a ``run_levels.py`` output folder into the load-test results tables (Markdown).

Client-side numbers come from the locustfile's per-turn CSVs, per-stage server timings from
``message_traces.steps_ms`` of this run's turns (matched on ``X-Request-ID``),
GPU memory and load from the ``nvidia-smi`` samples, CPU from the API process samples.

    python -m scripts.loadtest.report data/loadtest/<run>

Reads the database named in ``scripts/loadtest/loadtest.env``; writes ``results.md`` next to the inputs.
"""

# Standard library imports
import argparse
import asyncio
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Third-party imports
import numpy as np
from dotenv import load_dotenv
from sqlalchemy import text

ENV_FILE = Path(__file__).resolve().parent / "loadtest.env"
load_dotenv(ENV_FILE, override=True)

# Local imports
from config.settings import Config  # noqa: E402
from core.storage.database import Database  # noqa: E402

#: Server-side steps reported, in pipeline order (``steps_ms`` keys).
STEPS = ("guard", "router", "rewrite", "retrieval", "generation", "first_token", "total")
#: Columns of the locustfile's per-turn CSV.
TURN_COLUMNS = ("started_unix", "result", "ttft_ms", "e2e_ms")
MILLISECONDS_PER_SECOND = 1000
TRACES_SQL = text(
    "SELECT t.steps_ms, m.outcome FROM messages m JOIN message_traces t ON t.message_id = m.id "
    "WHERE m.role = 'assistant' AND m.request_id LIKE :pattern"
)


def percentiles(values: Sequence[float]) -> str:
    """``p50 / p95`` of ``values`` in whole milliseconds, or a dash when there are none."""
    if not values:
        return "-"
    p50, p95 = np.percentile(values, [50, 95])
    return f"{p50:.0f} / {p95:.0f}"


def read_csv(path: Path, columns: Optional[Sequence[str]] = None) -> List[Dict[str, str]]:
    """Rows of a CSV file (``columns`` when it has no header row), or ``[]`` when it is missing."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, fieldnames=columns))


class LevelReport:
    """Every number of one concurrency level, read from the run folder and the database."""

    def __init__(self, folder: Path, users: int, level: Dict[str, Any]):
        """
        Args:
            folder: Output folder of ``run_levels.py``.
            users: Concurrent users of this level.
            level: This level's entry in ``run.json``.
        """
        self.users = users
        self.tag = level["tag"]
        self._memory_before = level["gpu_memory_before_mib"]
        #: Another GPU job seen at the end of the level: its numbers are not clean.
        self.contaminated = bool(level.get("other_gpu_jobs_after"))
        self.turns = read_csv(folder / f"u{users}_turns.csv", TURN_COLUMNS)
        self.resources = read_csv(folder / f"u{users}_resources.csv")
        self.steps: Dict[str, List[float]] = {step: [] for step in STEPS}
        self.outcomes: Counter = Counter()

    async def load_traces(self, database: Database) -> None:
        """This level's per-stage timings and answer outcomes."""
        async with database.session() as session:
            rows = (await session.execute(TRACES_SQL, {"pattern": f"{self.tag}-%"})).all()
        for steps_ms, outcome in rows:
            self.outcomes[outcome] += 1
            for step in STEPS:
                if step in steps_ms:
                    self.steps[step].append(steps_ms[step])

    def _throughput(self, completed: List[Dict[str, str]]) -> float:
        """Completed turns per second, from the first request sent to the last answer finished."""
        starts = [float(row["started_unix"]) for row in self.turns]
        finishes = [float(row["started_unix"]) + float(row["e2e_ms"]) / MILLISECONDS_PER_SECOND for row in completed]
        span = max(finishes) - min(starts)
        return len(completed) / span if span > 0 else 0.0

    def client_row(self) -> List[str]:
        """Users, requests, completed turns/s, error rate, TTFT, E2E, VRAM, GPU and CPU load, RAM."""
        completed = [row for row in self.turns if row["result"] == "ok"]
        errors = Counter(row["result"] for row in self.turns if row["result"] != "ok")
        error_text = f"{sum(errors.values()) / len(self.turns):.1%}" if self.turns else "-"
        if errors:
            error_text += " (" + ", ".join(f"{name} ×{count}" for name, count in errors.most_common()) + ")"
        memory = [float(row["gpu_memory_mib"]) for row in self.resources]
        utilization = [float(row["gpu_util_percent"]) for row in self.resources]
        cpu = [float(row["api_cpu_percent"]) for row in self.resources]
        rss = [float(row["api_rss_mib"]) for row in self.resources]
        return [
            f"{self.users}{' (GPU shared!)' if self.contaminated else ''}",
            str(len(self.turns)),
            f"{self._throughput(completed):.2f}" if completed else "-",
            error_text,
            percentiles([float(row["ttft_ms"]) for row in completed if row["ttft_ms"]]),
            percentiles([float(row["e2e_ms"]) for row in completed]),
            f"{max(memory):.0f} (+{max(memory) - self._memory_before:.0f})" if memory else "-",
            f"{np.mean(utilization):.0f} / {max(utilization):.0f}" if utilization else "-",
            f"{np.mean(cpu):.0f} / {max(cpu):.0f}" if cpu else "-",
            f"{max(rss):.0f}" if rss else "-",
        ]

    def stage_row(self) -> List[str]:
        """Users, traced turns, p50/p95 of each pipeline step, outcome mix."""
        mix = ", ".join(f"{outcome} {count}" for outcome, count in self.outcomes.most_common())
        return [str(self.users), str(sum(self.outcomes.values()))] + [percentiles(self.steps[s]) for s in STEPS] + [mix]


def markdown_table(header: List[str], rows: List[List[str]]) -> str:
    """A GitHub Markdown table."""
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


async def build_report(folder: Path) -> str:
    """The Markdown results of the run in ``folder``."""
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    levels = [LevelReport(folder, int(users), level) for users, level in run["levels"].items()]
    database = Database(Config.Database.DATABASE_URL(), pool_size=1)
    database.connect()
    try:
        for level in levels:
            await level.load_traces(database)
    finally:
        await database.close()
    client = markdown_table(
        ["Users", "Requests", "Completed turns/s", "Refused", "TTFT p50 / p95 (ms)", "E2E p50 / p95 (ms)",
         "Peak GPU memory (MiB, +over idle)", "GPU util mean / max (%)", "API CPU mean / max (% of a core)",
         "API RSS peak (MiB)"],
        [level.client_row() for level in levels],
    )
    stages = markdown_table(
        ["Users", "Traced turns"] + [f"{step} p50 / p95" for step in STEPS] + ["Outcomes"],
        [level.stage_row() for level in levels],
    )
    return (
        f"Run {folder.name}: {run['duration']} per level against {run['host']}, started {run['started_at']}.\n\n"
        f"### Client side (Locust)\n\n{client}\n\n### Server stages (message_traces.steps_ms, ms)\n\n{stages}\n"
    )


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="Output folder of run_levels.py")
    args = parser.parse_args(argv)
    report = asyncio.run(build_report(args.folder))
    (args.folder / "results.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
