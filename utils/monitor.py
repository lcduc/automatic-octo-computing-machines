"""
Performance monitoring utilities for the chatbot.
Provides real-time performance metrics and monitoring capabilities.
"""

import time
import psutil
import logging
from collections import deque
from typing import Any, Dict, Optional
from datetime import datetime
import threading

from config.settings import Config

logger = logging.getLogger(__name__)

#: Bounded window of recent per-request latencies kept for percentile
#: calculation; ``total_response_time``/``request_count`` stay all-time.
_RECENT_LATENCY_WINDOW = 500


class PerformanceMonitor:
    """Monitor chatbot performance metrics in real-time."""

    def __init__(self):
        self.start_time = time.time()
        self.request_count = 0
        self.total_response_time = 0.0
        self.cache_hits = 0
        self.cache_misses = 0
        self.memory_usage_history = []
        self.cpu_usage_history = []
        self._recent_response_times: deque = deque(maxlen=_RECENT_LATENCY_WINDOW)
        self._stage_totals: Dict[str, float] = {}
        self._stage_counts: Dict[str, int] = {}
        self._lock = threading.Lock()

    def record_request(self, response_time: float, cache_hit: bool = False):
        """Record a request with its performance metrics."""
        with self._lock:
            self.request_count += 1
            self.total_response_time += response_time
            self._recent_response_times.append(response_time)
            if cache_hit:
                self.cache_hits += 1
            else:
                self.cache_misses += 1

    def record_stage_timings(self, latency_ms: float, query_id: str = "", **stage_ms: Optional[float]) -> None:
        """
        Record a per-query stage breakdown (e.g. retrieval/generation/intent, in ms).

        Also logs a warning immediately when the turn's total latency exceeds
        ``SLOW_REQUEST_THRESHOLD_MS``, since an aggregate average can hide a
        single very slow query.

        Args:
            latency_ms: Total wall-clock time for the turn, in milliseconds.
            query_id: Short identifier for the log line, if available.
            **stage_ms: Named stage durations in milliseconds; ``None`` values
                (stage skipped for this turn, e.g. no intent classification)
                are ignored.
        """
        with self._lock:
            for name, value in stage_ms.items():
                if value is None:
                    continue
                self._stage_totals[name] = self._stage_totals.get(name, 0.0) + value
                self._stage_counts[name] = self._stage_counts.get(name, 0) + 1

        threshold_ms = Config.Health.SLOW_REQUEST_THRESHOLD_MS()
        if latency_ms > threshold_ms:
            breakdown = ", ".join(
                f"{name}={value:.0f}ms" for name, value in stage_ms.items() if value is not None
            )
            logger.warning(
                "Slow query %s: %.0fms exceeds threshold %.0fms%s",
                query_id or "?",
                latency_ms,
                threshold_ms,
                f" ({breakdown})" if breakdown else "",
            )

    def record_system_metrics(self):
        """
        Sample CPU/memory usage into the rolling history.

        Uses a non-blocking CPU reading (percentage since the previous call), so
        this must never be invoked from a request handler — the background task
        manager samples it on a fixed interval instead.
        """
        try:
            memory_percent = psutil.virtual_memory().percent
            cpu_percent = psutil.cpu_percent(interval=None)

            with self._lock:
                self.memory_usage_history.append({
                    'timestamp': time.time(),
                    'memory_percent': memory_percent
                })
                self.cpu_usage_history.append({
                    'timestamp': time.time(),
                    'cpu_percent': cpu_percent
                })

                # Keep only last 100 measurements
                if len(self.memory_usage_history) > 100:
                    self.memory_usage_history = self.memory_usage_history[-100:]
                if len(self.cpu_usage_history) > 100:
                    self.cpu_usage_history = self.cpu_usage_history[-100:]

        except Exception as e:
            logger.debug(f"Failed to record system metrics: {e}")

    @staticmethod
    def _percentile(sorted_values, pct: float) -> float:
        """Nearest-rank percentile (``pct`` in 0-100) over an already-sorted sequence."""
        if not sorted_values:
            return 0.0
        if len(sorted_values) == 1:
            return sorted_values[0]
        rank = max(1, min(len(sorted_values), round(pct / 100 * len(sorted_values))))
        return sorted_values[rank - 1]

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get comprehensive performance statistics."""
        with self._lock:
            uptime = time.time() - self.start_time
            avg_response_time = (self.total_response_time / self.request_count) if self.request_count > 0 else 0

            total_cache_requests = self.cache_hits + self.cache_misses
            cache_hit_rate = (self.cache_hits / total_cache_requests * 100) if total_cache_requests > 0 else 0

            # Calculate recent memory and CPU usage
            recent_memory = self.memory_usage_history[-10:] if self.memory_usage_history else []
            recent_cpu = self.cpu_usage_history[-10:] if self.cpu_usage_history else []

            avg_memory = sum(m['memory_percent'] for m in recent_memory) / len(recent_memory) if recent_memory else 0
            avg_cpu = sum(c['cpu_percent'] for c in recent_cpu) / len(recent_cpu) if recent_cpu else 0

            sorted_recent = sorted(self._recent_response_times)
            stage_averages = {
                name: round(self._stage_totals[name] / self._stage_counts[name], 1)
                for name in self._stage_totals
                if self._stage_counts.get(name)
            }

            return {
                'uptime_seconds': uptime,
                'uptime_formatted': f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m {int(uptime % 60)}s",
                'total_requests': self.request_count,
                'average_response_time': round(avg_response_time, 3),
                'p50_response_time': round(self._percentile(sorted_recent, 50), 3),
                'p95_response_time': round(self._percentile(sorted_recent, 95), 3),
                'p99_response_time': round(self._percentile(sorted_recent, 99), 3),
                'cache_hit_rate': round(cache_hit_rate, 1),
                'cache_hits': self.cache_hits,
                'cache_misses': self.cache_misses,
                'average_memory_usage': round(avg_memory, 1),
                'average_cpu_usage': round(avg_cpu, 1),
                'requests_per_minute': round(self.request_count / (uptime / 60), 1) if uptime > 0 else 0,
                'stage_breakdown_ms': stage_averages,
                'timestamp': datetime.now().isoformat()
            }

    def get_health_status(self) -> str:
        """Get overall health status based on performance metrics."""
        stats = self.get_performance_stats()

        if stats['average_response_time'] > 5.0:
            return "degraded"
        elif stats['average_memory_usage'] > 80:
            return "memory_pressure"
        elif stats['average_cpu_usage'] > 90:
            return "cpu_pressure"
        elif stats['cache_hit_rate'] < 20:
            return "cache_inefficient"
        else:
            return "healthy"

    def reset_stats(self):
        """Reset all performance statistics."""
        with self._lock:
            self.start_time = time.time()
            self.request_count = 0
            self.total_response_time = 0.0
            self.cache_hits = 0
            self.cache_misses = 0
            self.memory_usage_history.clear()
            self.cpu_usage_history.clear()
            self._recent_response_times.clear()
            self._stage_totals.clear()
            self._stage_counts.clear()
            logger.info("Performance statistics reset")


# Global performance monitor instance
_performance_monitor = None


def get_performance_monitor() -> PerformanceMonitor:
    """Get the global performance monitor instance."""
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor()
    return _performance_monitor


def log_performance_summary():
    """Log a performance summary to the console."""
    monitor = get_performance_monitor()
    stats = monitor.get_performance_stats()
    health = monitor.get_health_status()

    print("\n" + "="*60)
    print(" CHATBOT PERFORMANCE SUMMARY")
    print("="*60)
    print(f"⏱️  Uptime: {stats['uptime_formatted']}")
    print(f" Total Requests: {stats['total_requests']}")
    print(f"⚡ Avg Response Time: {stats['average_response_time']}s "
          f"(p50={stats['p50_response_time']}s, p95={stats['p95_response_time']}s, p99={stats['p99_response_time']}s)")
    if stats['stage_breakdown_ms']:
        breakdown = ", ".join(f"{name}={value}ms" for name, value in stats['stage_breakdown_ms'].items())
        print(f" Stage Breakdown: {breakdown}")
    print(f" Cache Hit Rate: {stats['cache_hit_rate']}%")
    print(f"💾 Avg Memory Usage: {stats['average_memory_usage']}%")
    print(f"🖥️  Avg CPU Usage: {stats['average_cpu_usage']}%")
    print(f"📈 Requests/Min: {stats['requests_per_minute']}")
    print(f"🏥 Health Status: {health.upper()}")
    print("="*60)

