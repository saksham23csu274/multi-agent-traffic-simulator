"""Action validation layer: every signal command passes through here before reaching the engine."""

from __future__ import annotations

from collections import defaultdict, deque

from .config import EmergencyConfig, TrafficControlConfig
from .models import (
    ACTION_TYPES,
    GREEN,
    REASON_EMERGENCY,
    REQUEST_PHASE,
    IntersectionObservation,
    PriorityRequest,
    SignalAction,
    Verdict,
)


class ActionValidator:
    """Enforces phase legality, minimum/maximum green, priority eligibility, and fairness budgets.

    Yellow and all-red clearance intervals are enforced by the engine itself: a phase change
    always passes through both, and no command is accepted while a transition is in progress.
    """

    def __init__(self, timing: TrafficControlConfig, emergency: EmergencyConfig):
        self.timing = timing
        self.emergency = emergency
        self._priority_log: dict[str, deque[tuple[float, float]]] = defaultdict(deque)

    # -------------------------------------------------------------- priority fairness
    def priority_seconds(self, intersection_id: str, t: float) -> float:
        log = self._priority_log[intersection_id]
        while log and log[0][0] <= t - self.emergency.fairness_window_s:
            log.popleft()
        return sum(seconds for _, seconds in log)

    def record_priority(self, intersection_id: str, t: float, seconds: float) -> None:
        self._priority_log[intersection_id].append((t, seconds))

    @property
    def max_priority_green_s(self) -> float:
        return self.timing.max_green_s + self.emergency.max_priority_hold_s

    def screen_requests(
        self, obs: IntersectionObservation, requests: list[PriorityRequest]
    ) -> tuple[dict[str, PriorityRequest], list[tuple[PriorityRequest, str]]]:
        """Split requests into those an agent may act on and those denied (with reasons)."""
        eligible: dict[str, PriorityRequest] = {}
        denied: list[tuple[PriorityRequest, str]] = []
        budget = self.emergency.max_priority_share * self.emergency.fairness_window_s
        used = self.priority_seconds(obs.intersection_id, obs.simulation_time_s)
        for req in requests:
            if used >= budget:
                denied.append((req, "fairness_budget_exhausted"))
            elif req.phase_id == obs.current_phase and obs.phase_elapsed_s >= self.max_priority_green_s:
                denied.append((req, "max_priority_hold_reached"))
            else:
                eligible[req.request_id] = req
        return eligible, denied

    @staticmethod
    def conflicting_demand(obs: IntersectionObservation) -> bool:
        """True when any approach not served by the current phase has queued or approaching vehicles.

        Maximum green only applies while conflicting traffic is waiting, as in actuated control.
        """
        return any(
            m.phase_id != obs.current_phase and (m.queue_vehicles > 0 or m.approaching_vehicles > 0)
            for m in obs.movements
        )

    # -------------------------------------------------------------- action checks
    def validate(
        self,
        obs: IntersectionObservation,
        action: object,
        eligible: dict[str, PriorityRequest] | None = None,
    ) -> Verdict:
        if not isinstance(action, SignalAction):
            return Verdict(False, "malformed_action")
        if action.intersection_id != obs.intersection_id:
            return Verdict(False, "wrong_intersection")
        if action.action not in ACTION_TYPES:
            return Verdict(False, "unknown_action")
        if obs.stage != GREEN:
            return Verdict(False, "transition_in_progress")
        if action.action == REQUEST_PHASE and action.phase_id not in obs.valid_phases:
            return Verdict(False, "unknown_phase")
        duration = action.requested_duration_s
        if duration is not None and not 0 < duration <= self.timing.max_green_s:
            return Verdict(False, "invalid_duration")

        changes_phase = action.action == REQUEST_PHASE and action.phase_id != obs.current_phase
        priority = False
        if action.reason_code == REASON_EMERGENCY:
            req = (eligible or {}).get(action.request_id or "")
            if req is None:
                return Verdict(False, "priority_request_not_eligible")
            target = action.phase_id if changes_phase else obs.current_phase
            if req.phase_id != target:
                return Verdict(False, "priority_phase_mismatch")
            priority = True

        if changes_phase:
            if obs.phase_elapsed_s < self.timing.min_green_s:
                return Verdict(False, "min_green_not_met", priority)
            return Verdict(True, "phase_change", priority)
        if obs.phase_elapsed_s >= self.timing.max_green_s and self.conflicting_demand(obs):
            if priority and obs.phase_elapsed_s < self.max_priority_green_s:
                return Verdict(True, "priority_hold", True)
            return Verdict(False, "max_green_reached", priority)
        return Verdict(True, "hold", priority)
