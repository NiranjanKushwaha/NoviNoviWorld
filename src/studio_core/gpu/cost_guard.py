"""Budget guard: tracks paid GPU time, warns, and tells the worker when to shut the pod down."""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass

from ..util import read_json, write_json


@dataclass
class BudgetPolicy:
    budget_inr: float = 800.0
    hourly_inr: float = 91.0
    gst_pct: float = 0.0              # set 18 if the provider adds GST on top of the hourly rate
    warn_pct: float = 0.70
    hard_stop_pct: float = 0.95
    idle_minutes: float = 10.0
    max_session_minutes: float = 180.0
    billing_granularity_min: float = 1.0   # assumed billing step; rounded UP to stay conservative


@dataclass
class Decision:
    action: str     # "ok" | "warn" | "shutdown"
    reason: str
    spent_inr: float
    remaining_inr: float


class CostGuard:
    def __init__(self, state_path: str, policy: BudgetPolicy = None, clock=time.time):
        self.path, self.policy, self.clock = state_path, policy or BudgetPolicy(), clock
        self.state = {"closed_inr": 0.0, "session": None, "history": []}
        if os.path.exists(state_path):
            self.state.update(read_json(state_path))

    # ---- pricing ----
    def _cost_for(self, seconds: float) -> float:
        g = self.policy.billing_granularity_min
        mins = math.ceil(max(seconds, 0) / 60.0 / g - 1e-9) * g
        return mins / 60.0 * self.policy.hourly_inr * (1 + self.policy.gst_pct / 100.0)

    def session_cost(self) -> float:
        s = self.state["session"]
        return self._cost_for(self.clock() - s["start"]) if s else 0.0

    def spent(self) -> float:
        return round(self.state["closed_inr"] + self.session_cost(), 2)

    def remaining(self) -> float:
        return round(self.policy.budget_inr - self.spent(), 2)

    # ---- lifecycle ----
    def start_session(self) -> None:
        now = self.clock()
        self.state["session"] = {"start": now, "last_activity": now}
        self._save()

    def activity(self) -> None:
        if self.state["session"]:
            self.state["session"]["last_activity"] = self.clock()
            self._save()

    def end_session(self, reason: str = "done") -> float:
        s = self.state["session"]
        if not s:
            return 0.0
        cost = self.session_cost()
        self.state["closed_inr"] = round(self.state["closed_inr"] + cost, 2)
        self.state["history"].append({"start": s["start"], "end": self.clock(),
                                      "cost_inr": round(cost, 2), "reason": reason})
        self.state["session"] = None
        self._save()
        return cost

    # ---- decisions ----
    def check(self) -> Decision:
        p, spent = self.policy, self.spent()
        rem = round(p.budget_inr - spent, 2)
        s = self.state["session"]
        if spent >= p.budget_inr * p.hard_stop_pct:
            return Decision("shutdown", f"budget hard stop: spent Rs{spent} of Rs{p.budget_inr}", spent, rem)
        if s:
            now = self.clock()
            if (now - s["start"]) / 60.0 >= p.max_session_minutes:
                return Decision("shutdown", f"session longer than {p.max_session_minutes} min", spent, rem)
            if (now - s["last_activity"]) / 60.0 >= p.idle_minutes:
                return Decision("shutdown", f"idle for {p.idle_minutes} min", spent, rem)
        if spent >= p.budget_inr * p.warn_pct:
            return Decision("warn", f"{int(100 * spent / p.budget_inr)}% of budget used", spent, rem)
        return Decision("ok", "within budget", spent, rem)

    def can_afford(self, next_job_seconds: float) -> bool:
        projected = self.spent() + self._cost_for(next_job_seconds) - (
            self._cost_for(self.clock() - self.state["session"]["start"]) if self.state["session"] else 0.0)
        # session cost already counts running time; add only the extra billing the job could cause
        return projected <= self.policy.budget_inr * self.policy.hard_stop_pct

    def _save(self) -> None:
        write_json(self.path, self.state)


def estimate_cost(total_video_seconds: float, gpu_sec_per_video_sec: float, attempts: float,
                  policy: BudgetPolicy, setup_minutes: float = 30.0) -> dict:
    """Rough cost model: generation time + one-off setup, billed at the hourly rate."""
    gen_s = total_video_seconds * gpu_sec_per_video_sec * attempts
    guard = CostGuard.__new__(CostGuard)
    guard.policy = policy
    cost = guard._cost_for(gen_s + setup_minutes * 60)
    return {"gpu_hours": round((gen_s + setup_minutes * 60) / 3600, 2), "cost_inr": round(cost, 0),
            "generation_minutes": round(gen_s / 60, 1)}
