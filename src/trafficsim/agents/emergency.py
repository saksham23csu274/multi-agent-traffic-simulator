"""Emergency dispatch/routing agent and signal-priority coordinator."""

from __future__ import annotations

from typing import Any

from ..config import EmergencyConfig
from ..engine.base import TrafficEngine
from ..events import EventLog, MessageBus
from ..models import EMERGENCY, PriorityRequest, TripRecord
from ..routing import route_cost, shortest_path
from ..scenario import EmergencyRequest
from .monitor import TrafficMonitor


class EmergencyDispatchAgent:
    """Releases emergency vehicles, plans their routes, and reroutes them when conditions change."""

    agent_id = "emergency-dispatch"
    version = "1.0"

    def __init__(self, engine: TrafficEngine, requests: list[EmergencyRequest], cfg: EmergencyConfig,
                 monitor: TrafficMonitor, events: EventLog, bus: MessageBus):
        self.engine = engine
        self.network = engine.get_network_graph()
        self.cfg = cfg
        self.monitor = monitor
        self.events = events
        self.bus = bus
        self._pending = sorted(requests, key=lambda r: (r.release_s, r.id)) if cfg.enabled else []
        self.records: dict[str, dict[str, Any]] = {}
        self._active: list[str] = []
        self._next_check = 0.0
        bus.subscribe(self.agent_id, "incident")

    def _cost(self, edge_id: str) -> float:
        return self.monitor.edge_cost(edge_id, EMERGENCY)

    def active_vehicles(self) -> list[str]:
        return list(self._active)

    def update(self, t: float) -> None:
        while self._pending and self._pending[0].release_s <= t:
            self._dispatch(t, self._pending.pop(0))
        triggered = [m for m in self.bus.receive(self.agent_id) if m.topic == "incident"]
        if self.cfg.routing_strategy != "dynamic_shortest_path" or not self._active:
            return
        if triggered or t >= self._next_check:
            reason = "incident_update" if triggered else "periodic_check"
            for vid in list(self._active):
                self._consider_reroute(t, vid, reason)
            self._next_check = t + self.cfg.reroute_interval_s

    def _dispatch(self, t: float, req: EmergencyRequest) -> None:
        closed = self.engine.closed_edges()
        found = shortest_path(self.network, req.origin, req.destination, self._cost, blocked=closed)
        record = {
            "id": req.id, "vehicle_class": req.vehicle_class, "origin": req.origin,
            "destination": req.destination, "release_s": req.release_s, "dispatch_s": t,
            "arrival_s": None, "response_time_s": None, "status": "dispatched",
            "route_changes": 0, "stopped_time_s": None, "route_length_m": None,
            "initial_route": None, "initial_estimate_s": None,
        }
        self.records[req.id] = record
        if not found or not found[0]:
            record["status"] = "unroutable"
            self.events.emit(t, "emergency_unroutable", self.agent_id, vehicle_id=req.id)
            return
        route, estimate = found
        record["initial_route"] = route
        record["initial_estimate_s"] = round(estimate, 2)
        self.engine.add_vehicle(req.id, route, EMERGENCY, t, req.origin, req.destination)
        self._active.append(req.id)
        self.events.emit(t, "emergency_dispatched", self.agent_id, vehicle_id=req.id, route=route,
                         estimated_travel_s=round(estimate, 2), vehicle_class=req.vehicle_class)

    def _consider_reroute(self, t: float, vid: str, reason: str) -> None:
        info = self.engine.vehicle_info(vid)
        if info is None or info["state"] not in ("moving", "queued") or not info["remaining_route"]:
            return
        remaining = info["remaining_route"]
        node = self.network.edges[info["edge"]].to_node
        closed = self.engine.closed_edges()
        blocked_now = any(e in closed for e in remaining)
        current = float("inf") if blocked_now else route_cost(remaining, self._cost)
        best = shortest_path(self.network, node, info["destination"], self._cost, blocked=closed)
        if best is None or not best[0] or best[0] == remaining:
            return
        new_route, new_cost = best
        improvement_needed = 1 - self.cfg.reroute_threshold_percent / 100
        if blocked_now or new_cost < current * improvement_needed:
            if self.engine.reroute_vehicle(vid, new_route):
                self.records[vid]["route_changes"] += 1
                self.events.emit(
                    t, "emergency_rerouted", self.agent_id, vehicle_id=vid,
                    reason="route_blocked" if blocked_now else reason,
                    old_cost_s=None if blocked_now else round(current, 2), new_cost_s=round(new_cost, 2),
                    new_remaining_route=new_route,
                )

    def on_trips(self, trips: list[TripRecord]) -> None:
        for trip in trips:
            if trip.vehicle_class != EMERGENCY or trip.vehicle_id not in self.records:
                continue
            rec = self.records[trip.vehicle_id]
            rec.update(
                status="arrived",
                arrival_s=round(trip.arrival_s, 2),
                response_time_s=round(trip.arrival_s - rec["release_s"], 2),
                stopped_time_s=round(trip.waiting_time_s, 2),
                route_length_m=trip.route_length_m,
                route_changes=trip.route_changes,
            )
            if trip.vehicle_id in self._active:
                self._active.remove(trip.vehicle_id)
            self.events.emit(trip.arrival_s, "emergency_arrived", self.agent_id, vehicle_id=trip.vehicle_id,
                             response_time_s=rec["response_time_s"], stopped_time_s=rec["stopped_time_s"])


class PriorityCoordinator:
    """Issues time-bounded signal-priority requests to intersections ahead of emergency vehicles."""

    agent_id = "priority-coordinator"
    version = "1.0"

    def __init__(self, engine: TrafficEngine, cfg: EmergencyConfig, dispatcher: EmergencyDispatchAgent,
                 events: EventLog):
        self.engine = engine
        self.network = engine.get_network_graph()
        self.cfg = cfg
        self.dispatcher = dispatcher
        self.events = events
        self.active: dict[tuple[str, str], PriorityRequest] = {}
        self._expired: set[tuple[str, str]] = set()
        self.outcomes: dict[str, dict[str, Any]] = {}

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled and self.cfg.priority_enabled

    def update(self, t: float) -> dict[str, list[PriorityRequest]]:
        if not self.enabled:
            return {}
        seen: set[tuple[str, str]] = set()
        for vid in self.dispatcher.active_vehicles():
            for edge_id, eta in self.engine.remaining_route_etas(vid):
                if eta > self.cfg.priority_horizon_s:
                    break
                node = self.network.edges[edge_id].to_node
                phase = self.network.phase_for_edge(edge_id) if self.network.phases(node) else None
                key = (vid, node)
                if phase is None or key in self._expired:
                    continue
                seen.add(key)
                existing = self.active.get(key)
                issued = existing.issued_s if existing else t
                req = PriorityRequest(
                    request_id=f"{vid}@{node}", vehicle_id=vid, intersection_id=node, movement_id=edge_id,
                    phase_id=phase, eta_s=round(eta, 2), issued_s=issued,
                    expires_s=issued + self.cfg.priority_horizon_s + self.cfg.max_priority_hold_s,
                )
                if existing is None:
                    self.outcomes[req.request_id] = {"vehicle_id": vid, "intersection_id": node,
                                                     "approved": False, "denied": False, "end": None}
                    self.events.emit(t, "priority_requested", self.agent_id, request_id=req.request_id,
                                     vehicle_id=vid, intersection_id=node, phase_id=phase, eta_s=req.eta_s)
                self.active[key] = req

        for key, req in list(self.active.items()):
            if t > req.expires_s:
                self._close(t, key, "priority_expired", "time_limit")
                self._expired.add(key)
            elif key not in seen:
                info = self.engine.vehicle_info(req.vehicle_id)
                if info is None or info["state"] == "arrived":
                    self._close(t, key, "priority_cleared", "vehicle_arrived")
                elif req.movement_id in info["route"][: info["route_index"]]:
                    self._close(t, key, "priority_cleared", "vehicle_passed")
                elif req.movement_id not in info["route"][info["route_index"]:]:
                    self._close(t, key, "priority_cleared", "route_changed")

        grouped: dict[str, list[PriorityRequest]] = {}
        for req in self.active.values():
            grouped.setdefault(req.intersection_id, []).append(req)
        return grouped

    def _close(self, t: float, key: tuple[str, str], event: str, reason: str) -> None:
        req = self.active.pop(key)
        self.outcomes[req.request_id]["end"] = event
        self.events.emit(t, event, self.agent_id, request_id=req.request_id, vehicle_id=req.vehicle_id,
                         intersection_id=req.intersection_id, reason=reason)

    def record_decision(self, t: float, request_id: str, approved: bool, reason: str) -> None:
        outcome = self.outcomes.get(request_id)
        if outcome is None:
            return
        field_name = "approved" if approved else "denied"
        if not outcome[field_name]:
            outcome[field_name] = True
            self.events.emit(t, "priority_approved" if approved else "priority_denied", self.agent_id,
                             request_id=request_id, intersection_id=outcome["intersection_id"], reason=reason)

    def stats(self) -> dict[str, int]:
        outcomes = self.outcomes.values()
        return {
            "priority_requests": len(self.outcomes),
            "priority_approved": sum(1 for o in outcomes if o["approved"]),
            "priority_denied": sum(1 for o in outcomes if o["denied"]),
            "priority_expired": sum(1 for o in outcomes if o["end"] == "priority_expired"),
            "priority_cleared": sum(1 for o in outcomes if o["end"] == "priority_cleared"),
        }
