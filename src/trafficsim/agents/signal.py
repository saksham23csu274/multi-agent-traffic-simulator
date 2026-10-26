"""Intersection signal agents: fixed-time baseline and two adaptive policies."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import TrafficControlConfig
from ..models import HOLD, REASON_EMERGENCY, REQUEST_PHASE, IntersectionObservation, SignalAction


class SignalAgent(ABC):
    """Controls one intersection. Emergency priority requests take precedence over the policy."""

    policy_name = "abstract"
    version = "1.0"

    def __init__(self, intersection_id: str, timing: TrafficControlConfig, priority_enabled: bool = False):
        self.intersection_id = intersection_id
        self.agent_id = f"signal-agent-{intersection_id}"
        self.timing = timing
        self.priority_enabled = priority_enabled

    def decide(self, obs: IntersectionObservation) -> SignalAction:
        if self.priority_enabled and obs.emergency_requests:
            request = min(obs.emergency_requests, key=lambda r: (r.eta_s, r.request_id))
            if request.phase_id != obs.current_phase:
                return self._action(REQUEST_PHASE, request.phase_id, REASON_EMERGENCY, request.request_id)
            return self._action(HOLD, obs.current_phase, REASON_EMERGENCY, request.request_id)
        return self.policy(obs)

    @abstractmethod
    def policy(self, obs: IntersectionObservation) -> SignalAction: ...

    def _action(self, action: str, phase_id: str | None, reason: str = "policy",
                request_id: str | None = None, duration: float | None = None) -> SignalAction:
        return SignalAction(
            agent_id=self.agent_id,
            intersection_id=self.intersection_id,
            action=action,
            phase_id=phase_id,
            requested_duration_s=duration,
            reason_code=reason,
            request_id=request_id,
        )

    def _next_phase(self, obs: IntersectionObservation) -> str:
        phases = obs.valid_phases
        return phases[(phases.index(obs.current_phase) + 1) % len(phases)]


class FixedTimeAgent(SignalAgent):
    """Cycles through phases with a fixed green time. Also the safe fallback controller."""

    policy_name = "fixed_time"

    def policy(self, obs: IntersectionObservation) -> SignalAction:
        if len(obs.valid_phases) > 1 and obs.phase_elapsed_s >= self.timing.fixed_green_s:
            return self._action(REQUEST_PHASE, self._next_phase(obs), "fixed_cycle")
        return self._action(HOLD, obs.current_phase, "fixed_cycle")


class AdaptiveQueueAgent(SignalAgent):
    """Queue- and wait-weighted phase selection with minimum green and hysteresis."""

    policy_name = "adaptive_queue"

    def phase_demand(self, obs: IntersectionObservation) -> dict[str, float]:
        demand = {p: 0.0 for p in obs.valid_phases}
        for m in obs.movements:
            if m.phase_id in demand:
                demand[m.phase_id] += m.queue_vehicles + self.timing.wait_weight * m.mean_wait_s
        return demand

    def policy(self, obs: IntersectionObservation) -> SignalAction:
        if len(obs.valid_phases) < 2 or obs.phase_elapsed_s < self.timing.min_green_s:
            return self._action(HOLD, obs.current_phase, "min_green")
        demand = self.phase_demand(obs)
        current = demand[obs.current_phase]
        best = max((p for p in obs.valid_phases if p != obs.current_phase), key=lambda p: (demand[p], p))
        if demand[best] > 0 and (current == 0 or demand[best] > current * (1 + self.timing.hysteresis)):
            return self._action(REQUEST_PHASE, best, "higher_demand")
        if obs.phase_elapsed_s >= self.timing.max_green_s:
            waiting = {m.phase_id for m in obs.movements
                       if m.phase_id != obs.current_phase and (m.queue_vehicles or m.approaching_vehicles)}
            if waiting:
                target = best if best in waiting else min(waiting)
                return self._action(REQUEST_PHASE, target, "max_green")
        return self._action(HOLD, obs.current_phase, "current_phase_demand")


class MaxPressureAgent(AdaptiveQueueAgent):
    """Max-pressure control: serve the phase with the largest upstream minus downstream queue."""

    policy_name = "max_pressure"

    def phase_demand(self, obs: IntersectionObservation) -> dict[str, float]:
        pressure = {p: 0.0 for p in obs.valid_phases}
        for m in obs.movements:
            if m.phase_id in pressure:
                pressure[m.phase_id] += max(0.0, m.queue_vehicles - m.downstream_queue)
        return pressure


SIGNAL_AGENTS: dict[str, type[SignalAgent]] = {
    cls.policy_name: cls for cls in (FixedTimeAgent, AdaptiveQueueAgent, MaxPressureAgent)
}
