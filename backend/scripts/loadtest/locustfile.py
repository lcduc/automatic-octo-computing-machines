"""
Locust load test of ``POST /api/v1/chat/stream``, called the way the widget server calls it.

Each simulated visitor sends the widget server's ``X-Service-Token``, its own
``X-End-User-Id`` and ``X-Forwarded-For`` (the widget server forwards the visitor
IP), and asks the golden questions one after another with no think time, each in
a new conversation: N users keep N turns in flight. A refused visitor (503 busy,
429 limited) waits the response's ``Retry-After`` before asking again, as a person
reading "busy, try again shortly" in the widget would, instead of hammering the API. Besides Locust's entry for the
HTTP call (time to response headers, and every non-2xx as a failure), two entries
are reported per turn:

* ``ttft``: request sent -> first ``delta`` event (answered turns only)
* ``e2e``:  request sent -> ``done`` event

``X-Request-ID`` starts with ``LOADTEST_TAG`` so ``report.py`` can pick this run's
traces out of ``message_traces``; with ``LOADTEST_SAMPLES`` set, every turn's exact
timings are also appended to that CSV. Run it through ``run_levels.py``, or alone:

    LOADTEST_TAG=adhoc BFF_SERVICE_TOKEN=... locust -f scripts/loadtest/locustfile.py \
        --host http://127.0.0.1:8600 --headless -u 5 -r 5 -t 60s
"""

# Standard library imports
import csv
import itertools
import json
import os
import random
import time
import uuid
from pathlib import Path
from typing import Iterator, Optional, Tuple

# Third-party imports
from locust import HttpUser, task
from requests import RequestException

GOLDEN_QUERIES = Path(__file__).resolve().parents[1] / "demo_data" / "golden_queries.json"
CHAT_STREAM_PATH = "/api/v1/chat/stream"
#: Seconds one turn may take before Locust gives up on it (the API's own turn deadline is 90 s).
TURN_TIMEOUT_SECONDS = 120
#: Visitor IPs come from 198.18.0.0/15, the range reserved for benchmark tests (RFC 2544).
BENCHMARK_NET = "198.18"
MILLISECONDS_PER_SECOND = 1000
#: Wait after a refusal without a ``Retry-After`` header, and the cap on the header's value.
DEFAULT_RETRY_AFTER_SECONDS = 1.0
MAX_RETRY_AFTER_SECONDS = 10.0

QUERIES = [item["query"] for item in json.loads(GOLDEN_QUERIES.read_text(encoding="utf-8"))]
RUN_TAG = os.environ.get("LOADTEST_TAG", "adhoc")
SERVICE_TOKEN = os.environ.get("BFF_SERVICE_TOKEN", "")
#: CSV that gets one line per turn: start (unix s), ``ok`` or the failure, TTFT ms, E2E ms.
SAMPLES_PATH = os.environ.get("LOADTEST_SAMPLES", "")
_user_numbers = itertools.count(1)


def _ms(value: Optional[float]) -> str:
    """Milliseconds with one decimal, or empty when the turn never got there."""
    return "" if value is None else f"{value:.1f}"


def sse_events(lines: Iterator[str]) -> Iterator[Tuple[str, dict]]:
    """Yield ``(event, data)`` pairs from SSE lines, skipping ``: ping`` comments."""
    event: Optional[str] = None
    for line in lines:
        if line.startswith("event: "):
            event = line[len("event: "):]
        elif line.startswith("data: ") and event is not None:
            yield event, json.loads(line[len("data: "):])
            event = None


class WidgetVisitor(HttpUser):
    """One visitor of the chat widget, asking question after question."""

    def wait_time(self) -> float:
        """No think time, except the ``Retry-After`` of a refused request."""
        wait, self.retry_after = self.retry_after, 0.0
        return wait

    def on_start(self) -> None:
        """Give this visitor a fixed id, IP and starting question (reproducible per user number)."""
        number = next(_user_numbers)
        self.retry_after = 0.0
        self.visitor_id = f"{RUN_TAG}-v{number:04d}"
        self.headers = {
            "X-Service-Token": SERVICE_TOKEN,
            "X-End-User-Id": self.visitor_id,
            "X-Forwarded-For": f"{BENCHMARK_NET}.{number // 256}.{number % 256}",
        }
        offset = random.Random(number).randrange(len(QUERIES))
        self.questions = itertools.islice(itertools.cycle(QUERIES), offset, None)

    def _report(self, name: str, milliseconds: float) -> None:
        """Add one timing to Locust's statistics under ``name``."""
        self.environment.events.request.fire(
            request_type="SSE",
            name=name,
            response_time=milliseconds,
            response_length=0,
            exception=None,
            context={},
        )

    @staticmethod
    def _log_turn(started_unix: float, result: str, ttft_ms: Optional[float], e2e_ms: Optional[float]) -> None:
        """Append one turn to ``LOADTEST_SAMPLES`` (exact timings; Locust's percentiles are rounded)."""
        if not SAMPLES_PATH:
            return
        with open(SAMPLES_PATH, "a", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow([f"{started_unix:.3f}", result, _ms(ttft_ms), _ms(e2e_ms)])

    @task
    def ask(self) -> None:
        """Ask the next golden question in a new conversation and time the streamed answer."""
        headers = {**self.headers, "X-Request-ID": f"{RUN_TAG}-{uuid.uuid4().hex[:24]}"}
        started_unix, started = time.time(), time.perf_counter()
        first_token: Optional[float] = None
        finished: Optional[float] = None
        failure: Optional[str] = None
        with self.client.post(
            CHAT_STREAM_PATH,
            json={"message": next(self.questions)},
            headers=headers,
            name="chat/stream",
            stream=True,
            catch_response=True,
            timeout=TURN_TIMEOUT_SECONDS,
        ) as response:
            if response.status_code != 200:
                failure = f"HTTP {response.status_code}"
                retry_after = response.headers.get("Retry-After") if response.headers else None
                self.retry_after = min(float(retry_after or DEFAULT_RETRY_AFTER_SECONDS), MAX_RETRY_AFTER_SECONDS)
            else:
                response.encoding = "utf-8"  # text/event-stream without a charset would decode as Latin-1
                try:
                    for event, data in sse_events(response.iter_lines(decode_unicode=True)):
                        if event == "delta" and first_token is None:
                            first_token = time.perf_counter()
                        elif event == "error":
                            failure = f"error event: {data.get('message')}"
                            break
                        elif event == "done":
                            finished = time.perf_counter()
                            break
                    else:
                        failure = "stream ended without a done event"
                except RequestException as exc:
                    failure = type(exc).__name__
            if failure:
                response.failure(failure)
            else:
                response.success()
        e2e_ms = ttft_ms = None
        if finished is not None:
            e2e_ms = (finished - started) * MILLISECONDS_PER_SECOND
            self._report("e2e", e2e_ms)
            if first_token is not None:
                ttft_ms = (first_token - started) * MILLISECONDS_PER_SECOND
                self._report("ttft", ttft_ms)
        self._log_turn(started_unix, failure or "ok", ttft_ms, e2e_ms)
