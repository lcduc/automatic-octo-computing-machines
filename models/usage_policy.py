"""
Per-tier request limits, token budgets and the monthly spend cap (SEC-08, ID-02, ADM-09).
"""

# Standard library imports
from dataclasses import dataclass
from typing import Tuple

#: Micro-dollars per US dollar (costs are stored as integers).
MICRO_USD_PER_USD = 1_000_000


@dataclass(frozen=True)
class UsagePolicy:
    """Current limits; defaults come from the environment, the admin web can change them live."""

    anonymous_per_minute: int
    anonymous_per_hour: int
    anonymous_tokens_per_day: int
    user_per_minute: int
    user_per_hour: int
    user_tokens_per_day: int
    #: Tokens per client IP per day, across every visitor behind it (stops budget resets by clearing cookies).
    ip_tokens_per_day: int
    #: Monthly LLM spend cap in USD; 0 disables the cap.
    spend_cap_usd: float
    #: Share of the cap after which anonymous visitors are paused, so signed-in users keep the rest.
    anonymous_cutoff_ratio: float

    def for_caller(self, logged_in: bool) -> Tuple[int, int, int]:
        """``(requests per minute, requests per hour, tokens per day)`` for the caller's tier."""
        if logged_in:
            return self.user_per_minute, self.user_per_hour, self.user_tokens_per_day
        return self.anonymous_per_minute, self.anonymous_per_hour, self.anonymous_tokens_per_day

    def spend_limit_micro_usd(self, logged_in: bool) -> int:
        """Monthly spend at which this caller's turns stop (0 = no cap)."""
        cap = int(self.spend_cap_usd * MICRO_USD_PER_USD)
        return cap if logged_in else int(cap * self.anonymous_cutoff_ratio)
