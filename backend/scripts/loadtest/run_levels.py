"""
Run the chat load test at several concurrency levels, sampling the GPU and the API process.

Start the API first (see docs/PERFORMANCE.md), then, with the load-test venv:

    scripts/loadtest/venv/Scripts/python scripts/loadtest/run_levels.py --api-pid <pid>

A short warm-up run (not reported) loads the CUDA kernels first. Per level ``N`` it
writes to ``--out``: ``uN_turns.csv`` (one line per turn from the locustfile),
``uN_resources.csv`` (GPU memory and load, API process CPU and RSS, every 0.5 s),
Locust's own ``uN_stats.csv``, and ``run.json`` describing the run. ``report.py``
turns them into the results tables.
"""

# Standard library imports
import argparse
import csv
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Third-party imports
import psutil  # installed with Locust

HERE = Path(__file__).resolve().parent
LOCUSTFILE = HERE / "locustfile.py"
ENV_FILE = HERE / "loadtest.env"
DEFAULT_LEVELS = [1, 5, 10, 20, 50]
WARMUP_USERS = 2
SAMPLE_SECONDS = 0.5
BYTES_PER_MIB = 1024 * 1024
#: Seconds between checks while another job holds the GPU.
GPU_WAIT_SECONDS = 10
#: Seconds Locust waits for in-flight turns after the run time ends.
STOP_TIMEOUT_SECONDS = 30


def env_file_value(name: str) -> str:
    """One ``NAME=value`` from ``loadtest.env`` (the API's settings), or ``""``."""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip()
    return ""


def nvidia_smi(query: str) -> str:
    """Output of one ``nvidia-smi`` query in CSV without header or units."""
    result = subprocess.run(
        ["nvidia-smi", query, "--format=csv,noheader,nounits"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def other_gpu_jobs(api_pid: int) -> List[str]:
    """Python processes other than the API on the GPU (another model or eval job skews every number)."""
    rows = nvidia_smi("--query-compute-apps=pid,process_name").splitlines()
    return [row for row in rows if "python" in row.lower() and not row.startswith(f"{api_pid},")]


def wait_for_free_gpu(api_pid: int) -> None:
    """Block until no other Python process uses the GPU."""
    jobs = other_gpu_jobs(api_pid)
    if jobs:
        print(f"Waiting for other GPU jobs to finish: {jobs}", flush=True)
    while jobs:
        time.sleep(GPU_WAIT_SECONDS)
        jobs = other_gpu_jobs(api_pid)


def gpu_memory_used_mib() -> int:
    """Memory in use on the GPU, by every process."""
    return int(nvidia_smi("--query-gpu=memory.used").splitlines()[0])


class ResourceSampler(threading.Thread):
    """Every 0.5 s until stopped: GPU memory and utilisation, and the API process's CPU and RSS."""

    def __init__(self, pid: int, path: Path):
        """
        Args:
            pid: The API process.
            path: CSV file to write.
        """
        super().__init__(daemon=True)
        self._process = psutil.Process(pid)
        self._path = path
        self._stop_event = threading.Event()

    def run(self) -> None:
        """Sample until :meth:`stop`."""
        with self._path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["elapsed_s", "gpu_memory_mib", "gpu_util_percent", "api_cpu_percent", "api_rss_mib"])
            started = time.perf_counter()
            self._process.cpu_percent(None)
            while not self._stop_event.wait(SAMPLE_SECONDS):
                memory, utilization = nvidia_smi("--query-gpu=memory.used,utilization.gpu").split(", ")
                writer.writerow([
                    round(time.perf_counter() - started, 2), memory, utilization,
                    self._process.cpu_percent(None), round(self._process.memory_info().rss / BYTES_PER_MIB),
                ])

    def stop(self) -> None:
        """End sampling and wait for the file to be closed."""
        self._stop_event.set()
        self.join()


class LevelRunner:
    """Runs Locust for one level at a time against the API."""

    def __init__(self, host: str, api_pid: int, out: Path):
        """
        Args:
            host: Base URL of the API.
            api_pid: The API process, for resource sampling.
            out: Folder for every output file.
        """
        self._host = host
        self._api_pid = api_pid
        self._out = out

    def run(self, name: str, users: int, tag: str, duration: str) -> Dict[str, float]:
        """
        One closed-loop Locust run of ``users`` visitors for ``duration`` (e.g. ``90s``), files prefixed ``name``.

        Returns:
            Wall-clock start and end (unix seconds) of the run.
        """
        prefix = self._out / name
        sampler = ResourceSampler(self._api_pid, Path(f"{prefix}_resources.csv"))
        environment = {
            **os.environ,
            "LOADTEST_TAG": tag,
            "LOADTEST_SAMPLES": f"{prefix}_turns.csv",
            "BFF_SERVICE_TOKEN": env_file_value("BFF_SERVICE_TOKEN"),
        }
        started = time.time()
        sampler.start()
        try:
            subprocess.run(
                [sys.executable, "-m", "locust", "-f", str(LOCUSTFILE), "--headless", "--only-summary",
                 "--host", self._host, "-u", str(users), "-r", str(users), "-t", duration,
                 "--stop-timeout", str(STOP_TIMEOUT_SECONDS), "--csv", str(prefix)],
                env=environment, check=False,
            )
        finally:
            sampler.stop()
        return {"started_unix": started, "ended_unix": time.time()}


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-pid", type=int, required=True, help="PID of the API process")
    parser.add_argument("--levels", type=int, nargs="+", default=DEFAULT_LEVELS, help="Concurrent users per run")
    parser.add_argument("--duration", default="90s", help="Locust run time per level")
    parser.add_argument("--warmup", default="20s", help="Run time of the unreported warm-up (0s to skip)")
    parser.add_argument("--cooldown", type=float, default=15.0, help="Idle seconds between levels")
    parser.add_argument("--host", default=f"http://127.0.0.1:{env_file_value('PORT') or 8600}")
    parser.add_argument("--out", type=Path, default=Path("data/loadtest") / datetime.now().strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    run_id = args.out.name.replace("_", "-")
    runner = LevelRunner(args.host, args.api_pid, args.out)
    if args.warmup != "0s":
        wait_for_free_gpu(args.api_pid)
        runner.run("warmup", WARMUP_USERS, f"lt-{run_id}-warmup", args.warmup)
        time.sleep(args.cooldown)
    run = {"started_at": datetime.now(timezone.utc).isoformat(), "duration": args.duration, "host": args.host,
           "levels": {}}
    for users in args.levels:
        tag = f"lt-{run_id}-u{users}"
        wait_for_free_gpu(args.api_pid)
        print(f"=== {users} users (tag {tag})", flush=True)
        level = {"tag": tag, "gpu_memory_before_mib": gpu_memory_used_mib()}
        level.update(runner.run(f"u{users}", users, tag, args.duration))
        level["other_gpu_jobs_after"] = other_gpu_jobs(args.api_pid)
        if level["other_gpu_jobs_after"]:
            print(f"WARNING: another GPU job ran during this level: {level['other_gpu_jobs_after']}", flush=True)
        run["levels"][str(users)] = level
        (args.out / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
        time.sleep(args.cooldown)
    print(f"Results in {args.out}; next: python -m scripts.loadtest.report {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
