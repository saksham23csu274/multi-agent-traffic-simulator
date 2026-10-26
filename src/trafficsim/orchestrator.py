"""Simulation orchestrator: owns the clock, schedules agents, validates actions, and records results."""

from __future__ import annotations

import dataclasses
import platform
import random
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .agents import (
    SIGNAL_AGENTS,
    EmergencyDispatchAgent,
    FixedTimeAgent,
    IncidentManager,
    PriorityCoordinator,
    SignalAgent,
    TrafficMonitor,
)
from .config import RunConfig
from .engine import MesoEngine, TrafficEngine
from .events import EventLog, MessageBus
from .metrics import MetricsCollector
from .models import GREEN, PASSENGER, REQUEST_PHASE, IntersectionObservation, SignalAction
from .routing import shortest_path
from .scenario import Scenario, generate_departures, load_scenario
from .validation import ActionValidator

MAX_CONSECUTIVE_FAULTS = 3
EPS = 1e-9
STAGE_CODES = {"green": "g", "yellow": "y", "all_red": "r"}

AgentFactory = Callable[[str, RunConfig], SignalAgent]


@dataclass
class RunResult:
    run_id: str
    status: str
    manifest: dict[str, Any]
    summary: dict[str, Any]
    events: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    metrics: MetricsCollector
    network: dict[str, Any]
    output_dir: Path | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def default_agent_factory(intersection_id: str, config: RunConfig) -> SignalAgent:
    cls = SIGNAL_AGENTS[config.traffic_control.strategy]
    priority = config.emergency.enabled and config.emergency.priority_enabled
    return cls(intersection_id, config.traffic_control, priority_enabled=priority)


def make_run_id(config: RunConfig, scenario: Scenario) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")[:-3]
    return f"{scenario.id}_{config.traffic_control.strategy}_seed{config.random_seed}_{stamp}"


class Orchestrator:
    def __init__(self, config: RunConfig, scenario: Scenario | None = None,
                 agent_factory: AgentFactory | None = None,
                 progress: Callable[[float, float], None] | None = None):
        self.config = config
        self.scenario = scenario or load_scenario(config.scenario)
        self.agent_factory = agent_factory or default_agent_factory
        self.progress = progress
        self.run_id = make_run_id(config, self.scenario)

    def _build(self) -> None:
        cfg = self.config
        self.rng = random.Random(cfg.random_seed)
        self.events = EventLog()
        self.bus = MessageBus()
        self.network = self.scenario.network
        self.engine: TrafficEngine = MesoEngine(
            self.network,
            step_length_s=cfg.simulation.step_length_s,
            saturation_flow_vps_per_lane=cfg.simulation.saturation_flow_vps_per_lane,
            jam_spacing_m=cfg.simulation.jam_spacing_m,
            yellow_s=cfg.traffic_control.yellow_s,
            all_red_s=cfg.traffic_control.all_red_s,
            queue_jump=cfg.emergency.queue_jump,
            on_event=self._engine_event,
        )
        self.metrics = MetricsCollector(cfg.metrics.sample_interval_s)
        self.monitor = TrafficMonitor(self.engine, cfg.monitoring, cfg.simulation.saturation_flow_vps_per_lane,
                                      self.events, self.bus)
        self.incidents = IncidentManager(self.engine, self.scenario.incidents, self.events, self.bus)
        self.dispatcher = EmergencyDispatchAgent(self.engine, self.scenario.emergencies, cfg.emergency,
                                                 self.monitor, self.events, self.bus)
        self.coordinator = PriorityCoordinator(self.engine, cfg.emergency, self.dispatcher, self.events)
        self.validator = ActionValidator(cfg.traffic_control, cfg.emergency)
        self.agents: dict[str, SignalAgent] = {}
        self.fallbacks: dict[str, SignalAgent] = {}
        self.faults: dict[str, int] = {}
        self.decisions: list[dict[str, Any]] = []
        self.departures = generate_departures(self.scenario, cfg.simulation.duration_s, self.rng)
        self._departure_idx = 0
        self._edge_index = {eid: i for i, eid in enumerate(sorted(self.network.edges))}

    def _engine_event(self, time_s: float, type: str, source: str, **data: Any) -> None:
        if type == "vehicle_rerouted" and data.get("vehicle_class") == PASSENGER:
            self._passenger_reroutes += 1
            return  # aggregated in the summary instead of logged per vehicle
        self.events.emit(time_s, type, source, **data)

    # ------------------------------------------------------------------ main loop
    def run(self) -> RunResult:
        cfg = self.config
        self._passenger_reroutes = 0
        self._build()
        manifest = self._manifest()
        status, error = "completed", None
        started = time.perf_counter()
        steps = 0
        try:
            self.engine.start()
            for node in self.network.signalized_nodes:
                if self.network.phases(node):
                    self.agents[node] = self.agent_factory(node, cfg)
                    self.fallbacks[node] = FixedTimeAgent(node, cfg.traffic_control, priority_enabled=False)
                    self.faults[node] = 0
            self.events.emit(0.0, "run_started", "orchestrator", run_id=self.run_id,
                             strategy=cfg.traffic_control.strategy, seed=cfg.random_seed)
            dt = cfg.simulation.step_length_s
            next_decision = cfg.simulation.decision_interval_s
            next_sample = cfg.metrics.sample_interval_s
            t = 0.0
            while t < cfg.simulation.duration_s - EPS:
                self.incidents.update(t)
                self.dispatcher.update(t)
                self._release_departures(t + dt)
                step = self.engine.step()
                steps += 1
                t = step.time_s
                self.metrics.record_trips(step.completed)
                self.dispatcher.on_trips(step.completed)
                self.monitor.update(t, dt)
                if t >= next_decision - EPS:
                    self._decide(t)
                    next_decision += cfg.simulation.decision_interval_s
                if t >= next_sample - EPS:
                    self._sample(t)
                    next_sample += cfg.metrics.sample_interval_s
                if self.progress:
                    self.progress(t, cfg.simulation.duration_s)
                timeout = cfg.simulation.timeout_s
                if timeout is not None and time.perf_counter() - started > timeout:
                    status = "timeout"
                    self.events.emit(t, "run_timeout", "orchestrator", wall_clock_limit_s=timeout)
                    break
        except Exception as exc:  # preserve partial results on unexpected failure
            status = "failed"
            error = "".join(traceback.format_exception(exc))
            self.events.emit(self.engine.time_s, "run_failed", "orchestrator", error=repr(exc))
        finally:
            self.engine.close()
        wall = time.perf_counter() - started
        self.events.emit(self.engine.time_s, "run_finished", "orchestrator", status=status)

        records = list(self.dispatcher.records.values())
        summary = self.metrics.summary(
            counts=self.engine.counts(),
            duration_s=max(self.engine.time_s, cfg.simulation.step_length_s),
            congested_edge_seconds=self.monitor.congested_edge_seconds,
            emergency_records=records,
            priority_stats=self.coordinator.stats(),
            incidents=self.scenario.incidents,
            wall_clock_s=wall,
            steps=steps,
        )
        summary["traffic"]["passenger_reroutes"] = self._passenger_reroutes
        summary["traffic"]["vehicles_generated"] = len(self.departures)
        summary = {"run_id": self.run_id, "status": status, "label": cfg.display_label,
                   "strategy": cfg.traffic_control.strategy, "seed": cfg.random_seed,
                   "scenario_id": self.scenario.id, **summary}
        manifest["status"] = status
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        return RunResult(
            run_id=self.run_id, status=status, manifest=manifest, summary=summary,
            events=self.events.events, decisions=self.decisions, metrics=self.metrics,
            network=self.network.to_dict(), error=error,
        )

    def _release_departures(self, until_s: float) -> None:
        closed = self.engine.closed_edges()
        noise = self.scenario.route_noise
        while self._departure_idx < len(self.departures) and self.departures[self._departure_idx].depart_s <= until_s:
            dep = self.departures[self._departure_idx]
            self._departure_idx += 1
            weights = {eid: 1.0 + self.rng.uniform(0, noise) for eid in sorted(self.network.edges)}
            found = shortest_path(self.network, dep.origin, dep.destination,
                                  lambda e: self.network.edges[e].free_flow_time_s * weights[e], blocked=closed)
            if found is None or not found[0]:
                self.events.emit(dep.depart_s, "vehicle_unroutable", "orchestrator", vehicle_id=dep.vehicle_id)
                continue
            self.engine.add_vehicle(dep.vehicle_id, found[0], PASSENGER, dep.depart_s, dep.origin, dep.destination)

    # ------------------------------------------------------------------ decisions
    def _decide(self, t: float) -> None:
        requests = self.coordinator.update(t)
        for node in sorted(self.agents):
            obs = self.engine.get_intersection_state(node)
            if obs.stage != GREEN:
                continue
            eligible, denied = self.validator.screen_requests(obs, requests.get(node, []))
            for req, reason in denied:
                self.coordinator.record_decision(t, req.request_id, False, reason)
            obs = dataclasses.replace(obs, emergency_requests=tuple(eligible.values()))
            self._decide_one(t, node, obs, eligible)

    def _decide_one(self, t: float, node: str, obs: IntersectionObservation, eligible: dict) -> None:
        agent = self.agents[node]
        used_fallback = False
        started = time.perf_counter()
        try:
            action: Any = agent.decide(obs)
        except Exception as exc:
            action = None
            self.events.emit(t, "agent_fault", agent.agent_id, intersection_id=node, error=repr(exc))
        latency_ms = (time.perf_counter() - started) * 1000
        verdict = self.validator.validate(obs, action, eligible)

        if action is None or verdict.reason in ("malformed_action", "wrong_intersection", "unknown_action"):
            self.metrics.agent_faults += 1
            self.faults[node] += 1
            if action is not None:
                self.events.emit(t, "agent_fault", agent.agent_id, intersection_id=node, error=verdict.reason)
            if self.faults[node] >= MAX_CONSECUTIVE_FAULTS and agent is not self.fallbacks[node]:
                self.agents[node] = self.fallbacks[node]
                self.metrics.agents_replaced += 1
                self.events.emit(t, "agent_replaced_by_fallback", "orchestrator", intersection_id=node,
                                 failed_agent=agent.agent_id)
            self.metrics.record_decision(latency_ms, False, verdict.reason if action is not None else "agent_exception")
            action = self.fallbacks[node].decide(obs)
            verdict = self.validator.validate(obs, action, eligible)
            used_fallback = True
            self.metrics.fallback_decisions += 1
        else:
            self.faults[node] = 0

        result = None
        if verdict.accepted:
            result = self.engine.set_signal_action(node, action)
            if not result.accepted:
                self.metrics.engine_rejections += 1
            if verdict.priority and action.request_id:
                self.validator.record_priority(node, t, self.config.simulation.decision_interval_s)
                self.coordinator.record_decision(t, action.request_id, True, verdict.reason)
        elif verdict.priority and action.request_id and verdict.reason == "max_green_reached":
            self.coordinator.record_decision(t, action.request_id, False, verdict.reason)
        if not used_fallback:
            self.metrics.record_decision(latency_ms, verdict.accepted, verdict.reason)

        forced = False
        changing = verdict.accepted and action.action == REQUEST_PHASE and action.phase_id != obs.current_phase
        if (not changing and not (verdict.accepted and verdict.priority) and len(obs.valid_phases) > 1
                and obs.phase_elapsed_s >= self.config.traffic_control.max_green_s
                and self.validator.conflicting_demand(obs)):
            phases = obs.valid_phases
            nxt = phases[(phases.index(obs.current_phase) + 1) % len(phases)]
            self.engine.set_signal_action(node, SignalAction("orchestrator", node, REQUEST_PHASE, nxt,
                                                             reason_code="max_green_safety"))
            self.metrics.forced_phase_changes += 1
            self.events.emit(t, "forced_phase_change", "orchestrator", intersection_id=node,
                             from_phase=obs.current_phase, to_phase=nxt)
            forced = True

        if self.config.outputs.save_decisions:
            self.decisions.append({
                "time_s": round(t, 3),
                "intersection_id": node,
                "agent_id": getattr(action, "agent_id", None),
                "policy": (self.fallbacks[node] if used_fallback else agent).policy_name,
                "fallback": used_fallback,
                "phase": obs.current_phase,
                "phase_elapsed_s": round(obs.phase_elapsed_s, 2),
                "queues": {m.approach: m.queue_vehicles for m in obs.movements},
                "requests": [r.request_id for r in obs.emergency_requests],
                "action": getattr(action, "action", None),
                "target_phase": getattr(action, "phase_id", None),
                "reason_code": getattr(action, "reason_code", None),
                "accepted": verdict.accepted,
                "verdict": verdict.reason,
                "priority": verdict.priority,
                "engine_result": result.reason if result else None,
                "forced_change": forced,
                "latency_ms": round(latency_ms, 4),
            })

    # ------------------------------------------------------------------ sampling
    def _sample(self, t: float) -> None:
        snap = self.engine.snapshot()
        states = [self.engine.edge_state(e) for e in sorted(self.network.edges)]
        frame = {
            "t": round(t, 2),
            "occ": [round(s.occupancy_ratio, 2) for s in states],
            "q": [s.queue for s in states],
            "sig": {n: [s["phase"], STAGE_CODES[s["stage"]]] for n, s in snap["signals"].items()},
            "ev": [[e["id"], self._edge_index[e["edge"]], e["progress"]] for e in snap["emergency"]],
            "closed": [self._edge_index[e] for e in snap["closed"]],
        }
        self.metrics.sample(
            t,
            self.engine.counts(),
            max_edge_queue=max((s.queue for s in states), default=0),
            mean_occupancy=sum(s.occupancy_ratio for s in states) / len(states) if states else 0.0,
            congested_edges=len(self.monitor.congested),
            active_emergencies=len(self.dispatcher.active_vehicles()),
            frame=frame,
        )

    def _manifest(self) -> dict[str, Any]:
        cfg = self.config
        policy_cls = SIGNAL_AGENTS[cfg.traffic_control.strategy]
        return {
            "run_id": self.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "software_version": __version__,
            "python_version": platform.python_version(),
            "engine": cfg.simulation.engine,
            "random_seed": cfg.random_seed,
            "label": cfg.display_label,
            "config_file": cfg.source_path,
            "config": cfg.to_dict(),
            "scenario": {
                "id": self.scenario.id,
                "description": self.scenario.description,
                "file": self.scenario.source_path,
                "sha256": self.scenario.sha256,
                "nodes": len(self.network.nodes),
                "edges": len(self.network.edges),
                "signalized_intersections": len(self.network.signalized_nodes),
            },
            "policies": {
                "signal": {"name": policy_cls.policy_name, "version": policy_cls.version},
                "fallback": {"name": FixedTimeAgent.policy_name, "version": FixedTimeAgent.version},
                "emergency_dispatch": {"name": EmergencyDispatchAgent.agent_id, "version": EmergencyDispatchAgent.version},
                "priority_coordinator": {"name": PriorityCoordinator.agent_id, "version": PriorityCoordinator.version},
            },
        }


def run_simulation(config: RunConfig, output_root: str | Path | None = None, *,
                   agent_factory: AgentFactory | None = None, write_outputs: bool = True,
                   progress: Callable[[float, float], None] | None = None) -> RunResult:
    """Run one simulation and, unless disabled, write its outputs under ``output_root/<run_id>``."""
    orchestrator = Orchestrator(config, agent_factory=agent_factory, progress=progress)
    result = orchestrator.run()
    if write_outputs:
        from .outputs import write_run_outputs
        root = Path(output_root if output_root is not None else config.outputs.directory)
        result.output_dir = write_run_outputs(result, root / result.run_id, config)
    return result
