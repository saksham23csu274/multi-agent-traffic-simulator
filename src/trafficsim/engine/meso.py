"""Built-in mesoscopic queue-based traffic engine.

Each directed edge holds vehicles in two places: a *moving* set (vehicles travelling
toward the stop line, each with a precomputed arrival time) and a FIFO *queue* at the
stop line. Queues discharge at a saturation flow rate while the approach has a green
indication and the next edge has free storage (otherwise spillback blocks the queue).
Signals move through green -> yellow -> all-red -> green; vehicles never discharge on
yellow or all-red.
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..models import (
    ALL_RED,
    EMERGENCY,
    GREEN,
    HOLD,
    REQUEST_PHASE,
    YELLOW,
    ActionResult,
    EdgeState,
    IntersectionObservation,
    MovementObservation,
    SignalAction,
    StepResult,
    TripRecord,
)
from ..network import RoadNetwork
from ..routing import free_flow_cost, shortest_path
from ..scenario import Incident
from .base import EngineError, EventSink, TrafficEngine

EMERGENCY_SPEED_FACTOR = 1.15
MIN_DENSITY_FACTOR = {"passenger": 0.15, EMERGENCY: 0.5}
EPS = 1e-9


@dataclass
class _Vehicle:
    id: str
    vclass: str
    route: list[str]
    origin: str
    destination: str
    depart_s: float
    idx: int = 0
    state: str = "pending"  # pending | moving | queued | arrived
    insert_s: float | None = None
    edge_entry_s: float = 0.0
    ready_s: float = 0.0
    queue_enter_s: float = 0.0
    waiting_s: float = 0.0
    stops: int = 0
    distance_m: float = 0.0
    free_flow_s: float = 0.0
    route_changes: int = 0

    @property
    def edge(self) -> str:
        return self.route[self.idx]


@dataclass
class _Signal:
    phases: list[str]
    approaches: dict[str, tuple[str, ...]]
    index: int = 0
    stage: str = GREEN
    stage_elapsed: float = 0.0
    phase_elapsed: float = 0.0
    next_index: int | None = None

    @property
    def phase(self) -> str:
        return self.phases[self.index]


@dataclass
class _EdgeRuntime:
    moving: list[tuple[float, int, str]] = field(default_factory=list)
    queue: deque[str] = field(default_factory=deque)
    backlog: deque[str] = field(default_factory=deque)
    credit: float = 0.0


class MesoEngine(TrafficEngine):
    name = "meso"

    def __init__(
        self,
        network: RoadNetwork,
        *,
        step_length_s: float = 1.0,
        saturation_flow_vps_per_lane: float = 0.5,
        jam_spacing_m: float = 7.5,
        yellow_s: float = 3.0,
        all_red_s: float = 1.0,
        queue_jump: bool = True,
        on_event: EventSink | None = None,
    ):
        self.network = network
        self.dt = step_length_s
        self.sat = saturation_flow_vps_per_lane
        self.yellow_s = yellow_s
        self.all_red_s = all_red_s
        self.queue_jump = queue_jump
        self.on_event = on_event or (lambda *a, **k: None)
        self.capacity = {eid: e.storage_capacity(jam_spacing_m) for eid, e in network.edges.items()}
        self.edge_order = sorted(network.edges)
        self._approach = {eid: network.approach(eid) for eid in network.edges}
        self._t = 0.0
        self._started = False
        self._seq = 0
        self._edges: dict[str, _EdgeRuntime] = {}
        self._vehicles: dict[str, _Vehicle] = {}
        self._pending: list[tuple[float, int, str]] = []
        self._signals: dict[str, _Signal] = {}
        self._closed: dict[str, set[str]] = {}
        self._slow: dict[str, dict[str, float]] = {}
        self._arrived = 0
        self._free_cost = free_flow_cost(network)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._t = 0.0
        self._edges = {eid: _EdgeRuntime() for eid in self.network.edges}
        self._signals = {}
        for node in self.network.signalized_nodes:
            phases = self.network.phases(node)
            if phases:
                self._signals[node] = _Signal(
                    phases=[p.id for p in phases],
                    approaches={p.id: p.approaches for p in phases},
                )
        self._started = True

    @property
    def time_s(self) -> float:
        return self._t

    def get_network_graph(self) -> RoadNetwork:
        return self.network

    def _require_started(self) -> None:
        if not self._started:
            raise EngineError("Engine has not been started")

    # ------------------------------------------------------------------ vehicles
    def add_vehicle(self, vehicle_id, route, vehicle_class, depart_s, origin, destination) -> None:
        self._require_started()
        if vehicle_id in self._vehicles:
            raise EngineError(f"Duplicate vehicle id {vehicle_id}")
        if not route:
            raise EngineError(f"Vehicle {vehicle_id} has an empty route")
        for a, b in zip(route, route[1:]):
            if self.network.edges[a].to_node != self.network.edges[b].from_node:
                raise EngineError(f"Vehicle {vehicle_id} route is not connected at {a} -> {b}")
        self._vehicles[vehicle_id] = _Vehicle(vehicle_id, vehicle_class, list(route), origin, destination, depart_s)
        self._seq += 1
        heapq.heappush(self._pending, (depart_s, self._seq, vehicle_id))

    def reroute_vehicle(self, vehicle_id: str, remaining_route: list[str]) -> bool:
        """Replace the route after the vehicle's current edge. Returns False if not applicable."""
        v = self._vehicles.get(vehicle_id)
        if v is None or v.state in ("arrived", "pending") or not remaining_route:
            return False
        if self.network.edges[remaining_route[0]].from_node != self.network.edges[v.edge].to_node:
            return False
        v.route = v.route[: v.idx + 1] + list(remaining_route)
        v.route_changes += 1
        return True

    def vehicle_info(self, vehicle_id: str) -> dict[str, Any] | None:
        v = self._vehicles.get(vehicle_id)
        if v is None:
            return None
        return {
            "id": v.id,
            "class": v.vclass,
            "state": v.state,
            "edge": v.edge if v.state in ("moving", "queued") else None,
            "route": list(v.route),
            "route_index": v.idx,
            "remaining_route": v.route[v.idx + 1:],
            "waiting_s": v.waiting_s,
            "route_changes": v.route_changes,
            "destination": v.destination,
        }

    def _class_speed(self, vclass: str) -> float:
        return EMERGENCY_SPEED_FACTOR if vclass == EMERGENCY else 1.0

    def _speed_factor(self, edge_id: str) -> float:
        factor = 1.0
        for factors in self._slow.values():
            factor = min(factor, factors.get(edge_id, 1.0))
        return factor

    def _occupancy(self, edge_id: str) -> int:
        rt = self._edges[edge_id]
        return len(rt.moving) + len(rt.queue)

    def _has_room(self, edge_id: str) -> bool:
        return edge_id not in self.closed_edges() and self._occupancy(edge_id) < self.capacity[edge_id]

    def _travel_time(self, edge_id: str, vclass: str) -> float:
        edge = self.network.edges[edge_id]
        density = self._occupancy(edge_id) / self.capacity[edge_id]
        density_factor = max(MIN_DENSITY_FACTOR.get(vclass, 0.15), 1.0 - density)
        speed = edge.speed_limit_mps * self._speed_factor(edge_id) * density_factor * self._class_speed(vclass)
        return edge.length_m / speed

    def _enter_edge(self, v: _Vehicle, edge_id: str, t: float) -> None:
        edge = self.network.edges[edge_id]
        travel = self._travel_time(edge_id, v.vclass)
        v.state = "moving"
        v.edge_entry_s = t
        v.ready_s = t + travel
        v.distance_m += edge.length_m
        v.free_flow_s += edge.free_flow_time_s
        self._seq += 1
        heapq.heappush(self._edges[edge_id].moving, (v.ready_s, self._seq, v.id))

    def _complete(self, v: _Vehicle, arrival_s: float) -> TripRecord:
        v.state = "arrived"
        self._arrived += 1
        travel = arrival_s - v.depart_s
        insert = v.insert_s if v.insert_s is not None else v.depart_s
        return TripRecord(
            vehicle_id=v.id,
            vehicle_class=v.vclass,
            origin=v.origin,
            destination=v.destination,
            depart_s=v.depart_s,
            insert_s=insert,
            arrival_s=arrival_s,
            travel_time_s=travel,
            waiting_time_s=v.waiting_s,
            depart_delay_s=insert - v.depart_s,
            stops=v.stops,
            route_length_m=v.distance_m,
            free_flow_time_s=v.free_flow_s,
            time_loss_s=max(0.0, travel - v.free_flow_s),
            route_changes=v.route_changes,
        )

    # ------------------------------------------------------------------ signals
    def _is_green(self, edge_id: str) -> bool:
        node = self.network.edges[edge_id].to_node
        sig = self._signals.get(node)
        if sig is None:
            return True  # unsignalized / boundary node: free discharge
        return sig.stage == GREEN and self._approach[edge_id] in sig.approaches[sig.phase]

    def _advance_signals(self, dt: float) -> None:
        for node, sig in self._signals.items():
            sig.stage_elapsed += dt
            if sig.stage == GREEN:
                sig.phase_elapsed += dt
            elif sig.stage == YELLOW and sig.stage_elapsed >= self.yellow_s - EPS:
                sig.stage, sig.stage_elapsed = ALL_RED, 0.0
            elif sig.stage == ALL_RED and sig.stage_elapsed >= self.all_red_s - EPS:
                sig.index = sig.next_index if sig.next_index is not None else sig.index
                sig.stage, sig.stage_elapsed, sig.phase_elapsed, sig.next_index = GREEN, 0.0, 0.0, None
                self.on_event(self._t, "signal_green", node, phase_id=sig.phase)

    def set_signal_action(self, intersection_id: str, action: SignalAction) -> ActionResult:
        self._require_started()
        sig = self._signals.get(intersection_id)
        if sig is None:
            return ActionResult(False, "unknown_intersection")
        if action.action == HOLD:
            return ActionResult(True, "hold")
        if action.action != REQUEST_PHASE:
            return ActionResult(False, "unknown_action")
        if action.phase_id not in sig.phases:
            return ActionResult(False, "unknown_phase")
        if sig.stage != GREEN:
            return ActionResult(False, "transition_in_progress")
        if action.phase_id == sig.phase:
            return ActionResult(True, "already_active")
        sig.next_index = sig.phases.index(action.phase_id)
        sig.stage, sig.stage_elapsed = YELLOW, 0.0
        return ActionResult(True, "transition_started")

    def get_intersection_state(self, intersection_id: str) -> IntersectionObservation:
        self._require_started()
        sig = self._signals.get(intersection_id)
        if sig is None:
            raise EngineError(f"Unknown signalized intersection {intersection_id}")
        movements = []
        for eid in self.network.in_edges[intersection_id]:
            rt = self._edges[eid]
            waits = [self._t - self._vehicles[vid].queue_enter_s for vid in rt.queue]
            reverse = self.network.reverse_edge(eid)
            outs = [o for o in self.network.out_edges[intersection_id] if o != reverse]
            down_q = sum(len(self._edges[o].queue) for o in outs) / len(outs) if outs else 0.0
            blocked = any(not self._has_room(o) for o in outs) if outs else False
            movements.append(
                MovementObservation(
                    id=eid,
                    approach=self._approach[eid],
                    phase_id=self.network.phase_for_edge(eid),
                    queue_vehicles=len(rt.queue),
                    mean_wait_s=round(sum(waits) / len(waits), 3) if waits else 0.0,
                    approaching_vehicles=len(rt.moving),
                    downstream_queue=round(down_q, 3),
                    downstream_blocked=blocked,
                )
            )
        return IntersectionObservation(
            simulation_time_s=self._t,
            intersection_id=intersection_id,
            current_phase=sig.phase,
            stage=sig.stage,
            phase_elapsed_s=sig.phase_elapsed,
            valid_phases=tuple(sig.phases),
            movements=tuple(movements),
        )

    # ------------------------------------------------------------------ incidents
    def apply_incident(self, incident: Incident) -> ActionResult:
        if incident.kind == "closure":
            self._closed[incident.id] = set(incident.edges)
        else:
            self._slow[incident.id] = {e: incident.speed_factor for e in incident.edges}
        return ActionResult(True, "applied")

    def clear_incident(self, incident: Incident) -> ActionResult:
        found = self._closed.pop(incident.id, None) is not None
        found = self._slow.pop(incident.id, None) is not None or found
        return ActionResult(found, "cleared" if found else "not_active")

    def closed_edges(self) -> frozenset[str]:
        if not self._closed:
            return frozenset()
        return frozenset().union(*self._closed.values())

    # ------------------------------------------------------------------ stepping
    def step(self) -> StepResult:
        self._require_started()
        self._t += self.dt
        t = self._t
        result = StepResult(time_s=t)
        self._advance_signals(self.dt)
        self._arrive_at_stop_lines(t, result)
        self._discharge(t)
        self._insert(t)
        return result

    def _arrive_at_stop_lines(self, t: float, result: StepResult) -> None:
        for eid in self.edge_order:
            rt = self._edges[eid]
            while rt.moving and rt.moving[0][0] <= t + EPS:
                ready, _, vid = heapq.heappop(rt.moving)
                v = self._vehicles[vid]
                if v.idx == len(v.route) - 1:
                    result.completed.append(self._complete(v, ready))
                    continue
                v.state = "queued"
                v.queue_enter_s = ready
                if v.vclass == EMERGENCY and self.queue_jump:
                    # Ordinary vehicles yield: insert behind any emergency vehicles already at the front.
                    pos = 0
                    while pos < len(rt.queue) and self._vehicles[rt.queue[pos]].vclass == EMERGENCY:
                        pos += 1
                    rt.queue.insert(pos, vid)
                else:
                    rt.queue.append(vid)

    def _discharge(self, t: float) -> None:
        closed = self.closed_edges()
        for eid in self.edge_order:
            rt = self._edges[eid]
            if not self._is_green(eid):
                rt.credit = 0.0
                continue
            # Credit builds from the start of green (start-up lost time) and is capped, so a
            # vehicle arriving on an established green with no queue passes without stopping.
            rate = self.sat * self.network.edges[eid].lanes * self.dt
            rt.credit = min(rt.credit + rate, max(1.0, rate))
            while rt.credit >= 1.0 - EPS and rt.queue:
                v = self._vehicles[rt.queue[0]]
                nxt = v.route[v.idx + 1]
                if nxt in closed and not self._reroute_around_closure(v, closed):
                    break
                nxt = v.route[v.idx + 1]
                if not self._has_room(nxt):
                    break
                rt.queue.popleft()
                rt.credit -= 1.0
                waited = max(0.0, t - v.queue_enter_s)
                v.waiting_s += waited
                if waited >= 1.0:
                    v.stops += 1
                v.idx += 1
                self._enter_edge(v, nxt, t)

    def _reroute_around_closure(self, v: _Vehicle, closed: frozenset[str]) -> bool:
        node = self.network.edges[v.edge].to_node
        found = shortest_path(self.network, node, v.destination, self._free_cost, blocked=closed)
        if found is None or not found[0]:
            return False
        v.route = v.route[: v.idx + 1] + found[0]
        v.route_changes += 1
        self.on_event(self._t, "vehicle_rerouted", v.id, reason="edge_closed", vehicle_class=v.vclass)
        return True

    def _insert(self, t: float) -> None:
        while self._pending and self._pending[0][0] <= t + EPS:
            _, _, vid = heapq.heappop(self._pending)
            v = self._vehicles[vid]
            backlog = self._edges[v.route[0]].backlog
            if v.vclass == EMERGENCY:
                backlog.appendleft(vid)
            else:
                backlog.append(vid)
        for eid in self.edge_order:
            backlog = self._edges[eid].backlog
            while backlog and self._has_room(eid):
                v = self._vehicles[backlog.popleft()]
                v.insert_s = t
                v.idx = 0
                self._enter_edge(v, eid, t)

    # ------------------------------------------------------------------ inspection
    def edge_state(self, edge_id: str) -> EdgeState:
        rt = self._edges[edge_id]
        return EdgeState(
            edge_id=edge_id,
            occupancy=len(rt.moving) + len(rt.queue),
            capacity=self.capacity[edge_id],
            queue=len(rt.queue),
            moving=len(rt.moving),
            speed_factor=self._speed_factor(edge_id),
            closed=edge_id in self.closed_edges(),
        )

    def remaining_route_etas(self, vehicle_id: str) -> list[tuple[str, float]]:
        """Estimated seconds until the vehicle reaches the end of each remaining edge."""
        v = self._vehicles.get(vehicle_id)
        if v is None or v.state not in ("moving", "queued"):
            return []
        rate = lambda e: self.sat * self.network.edges[e].lanes  # noqa: E731
        rt = self._edges[v.edge]
        if v.state == "moving":
            eta = max(0.0, v.ready_s - self._t)
        else:
            eta = rt.queue.index(v.id) / rate(v.edge)
        etas = [(v.edge, eta)]
        for eid in v.route[v.idx + 1:]:
            eta += self._travel_time(eid, v.vclass) + len(self._edges[eid].queue) / rate(eid)
            etas.append((eid, eta))
        return etas

    def counts(self) -> dict[str, int]:
        in_network = sum(len(rt.moving) + len(rt.queue) for rt in self._edges.values())
        waiting_insert = sum(len(rt.backlog) for rt in self._edges.values())
        return {
            "in_network": in_network,
            "queued": sum(len(rt.queue) for rt in self._edges.values()),
            "waiting_to_insert": waiting_insert,
            "not_yet_departed": len(self._pending),
            "arrived": self._arrived,
        }

    def snapshot(self) -> dict[str, Any]:
        signals = {
            node: {"phase": sig.phase, "stage": sig.stage, "next": sig.phases[sig.next_index] if sig.next_index is not None else None}
            for node, sig in self._signals.items()
        }
        emergency = []
        for v in self._vehicles.values():
            if v.vclass == EMERGENCY and v.state in ("moving", "queued"):
                if v.state == "moving":
                    span = max(EPS, v.ready_s - v.edge_entry_s)
                    progress = min(1.0, max(0.0, (self._t - v.edge_entry_s) / span))
                else:
                    progress = 1.0
                emergency.append({"id": v.id, "edge": v.edge, "progress": round(progress, 3)})
        return {
            "t": self._t,
            "edges": {
                eid: (len(rt.moving) + len(rt.queue), len(rt.queue)) for eid, rt in self._edges.items()
            },
            "signals": signals,
            "emergency": emergency,
            "closed": sorted(self.closed_edges()),
        }
