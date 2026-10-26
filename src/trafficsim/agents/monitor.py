"""Traffic monitoring service and incident manager."""

from __future__ import annotations

from ..config import MonitoringConfig
from ..engine.base import TrafficEngine
from ..engine.meso import EMERGENCY_SPEED_FACTOR, MIN_DENSITY_FACTOR
from ..events import EventLog, MessageBus
from ..models import EMERGENCY, Message
from ..scenario import Incident


class TrafficMonitor:
    """Tracks per-edge congestion with hysteresis and estimates current edge travel costs."""

    agent_id = "traffic-monitor"

    def __init__(self, engine: TrafficEngine, cfg: MonitoringConfig, saturation_flow: float,
                 events: EventLog, bus: MessageBus):
        self.engine = engine
        self.network = engine.get_network_graph()
        self.cfg = cfg
        self.sat = saturation_flow
        self.events = events
        self.bus = bus
        self.congested: set[str] = set()
        self.congested_edge_seconds = 0.0

    def update(self, t: float, dt: float) -> None:
        for eid in sorted(self.network.edges):
            ratio = self.engine.edge_state(eid).occupancy_ratio
            if eid not in self.congested and ratio >= self.cfg.congestion_threshold:
                self.congested.add(eid)
                self._publish(t, "congestion_start", eid, ratio)
            elif eid in self.congested and ratio <= self.cfg.clear_threshold:
                self.congested.discard(eid)
                self._publish(t, "congestion_end", eid, ratio)
        self.congested_edge_seconds += dt * len(self.congested)

    def _publish(self, t: float, kind: str, edge_id: str, ratio: float) -> None:
        self.events.emit(t, kind, self.agent_id, edge_id=edge_id, occupancy_ratio=round(ratio, 3))
        self.bus.publish(Message("congestion", self.agent_id, t, {"kind": kind, "edge_id": edge_id}))

    def edge_cost(self, edge_id: str, vehicle_class: str = EMERGENCY) -> float:
        """Estimated seconds to traverse an edge now: travel time plus queue discharge delay."""
        edge = self.network.edges[edge_id]
        state = self.engine.edge_state(edge_id)
        density_factor = max(MIN_DENSITY_FACTOR.get(vehicle_class, 0.15), 1.0 - state.occupancy_ratio)
        class_factor = EMERGENCY_SPEED_FACTOR if vehicle_class == EMERGENCY else 1.0
        speed = edge.speed_limit_mps * state.speed_factor * density_factor * class_factor
        return edge.length_m / speed + state.queue / (self.sat * edge.lanes)


class IncidentManager:
    """Activates and resolves scheduled incidents and notifies subscribers."""

    agent_id = "incident-manager"

    def __init__(self, engine: TrafficEngine, incidents: list[Incident], events: EventLog, bus: MessageBus):
        self.engine = engine
        self.events = events
        self.bus = bus
        self._pending = sorted(incidents, key=lambda i: (i.start_s, i.id))
        self._active: list[Incident] = []

    def update(self, t: float) -> None:
        while self._pending and self._pending[0].start_s <= t:
            inc = self._pending.pop(0)
            self.engine.apply_incident(inc)
            self._active.append(inc)
            self._notify(t, "incident_start", inc)
        for inc in [i for i in self._active if i.end_s is not None and i.end_s <= t]:
            self.engine.clear_incident(inc)
            self._active.remove(inc)
            self._notify(t, "incident_end", inc)

    def _notify(self, t: float, kind: str, inc: Incident) -> None:
        self.events.emit(t, kind, self.agent_id, incident_id=inc.id, kind=inc.kind, edges=list(inc.edges),
                         speed_factor=inc.speed_factor)
        self.bus.publish(Message("incident", self.agent_id, t, {"kind": kind, "incident_id": inc.id,
                                                               "edges": list(inc.edges)}))
