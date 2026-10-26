"""Scenario loading: network, traffic demand, incidents, and emergency requests."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .network import NetworkError, RoadNetwork, build_network
from .routing import free_flow_cost, shortest_path

INCIDENT_KINDS = ("closure", "slowdown")


class ScenarioError(ValueError):
    """Raised when a scenario definition is invalid."""


@dataclass(frozen=True)
class DemandFlow:
    origin: str
    destination: str
    vehicles_per_hour: float
    start_s: float = 0.0
    end_s: float | None = None


@dataclass(frozen=True)
class Incident:
    id: str
    edges: tuple[str, ...]
    start_s: float
    end_s: float | None = None
    kind: str = "closure"
    speed_factor: float = 1.0


@dataclass(frozen=True)
class EmergencyRequest:
    id: str
    origin: str
    destination: str
    release_s: float
    vehicle_class: str = "ambulance"


@dataclass(frozen=True)
class Departure:
    vehicle_id: str
    depart_s: float
    origin: str
    destination: str


@dataclass
class Scenario:
    id: str
    description: str
    network: RoadNetwork
    demand: list[DemandFlow] = field(default_factory=list)
    incidents: list[Incident] = field(default_factory=list)
    emergencies: list[EmergencyRequest] = field(default_factory=list)
    route_noise: float = 0.2
    source_path: str | None = None
    sha256: str | None = None


def _expand_nodes(value: Any, network: RoadNetwork, key: str) -> list[str]:
    if value == "boundary":
        return sorted(n.id for n in network.nodes.values() if not n.signalized)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    raise ScenarioError(f"Demand '{key}' must be a node id, a list of node ids, or 'boundary'")


def _parse_demand(items: list[dict[str, Any]], network: RoadNetwork) -> list[DemandFlow]:
    flows: list[DemandFlow] = []
    for item in items:
        origins = _expand_nodes(item.get("origins", item.get("origin")), network, "origin")
        dests = _expand_nodes(item.get("destinations", item.get("destination")), network, "destination")
        vph = float(item["vehicles_per_hour"])
        if vph < 0:
            raise ScenarioError("vehicles_per_hour must be non-negative")
        for o in origins:
            for d in dests:
                if o != d:
                    flows.append(DemandFlow(o, d, vph, float(item.get("start_s", 0)), item.get("end_s")))
    return flows


def scenario_from_dict(data: dict[str, Any], source_path: str | None = None, sha256: str | None = None) -> Scenario:
    allowed = {"id", "description", "network", "demand", "incidents", "emergencies", "route_noise"}
    unknown = set(data) - allowed
    if unknown:
        raise ScenarioError(f"Unknown scenario key(s): {sorted(unknown)}")
    try:
        network = build_network(data.get("network") or {"type": "grid"})
    except NetworkError as exc:
        raise ScenarioError(str(exc)) from exc
    try:
        demand = _parse_demand(data.get("demand") or [], network)
        incidents = [
            Incident(
                id=str(i["id"]),
                edges=tuple(i["edges"]),
                start_s=float(i["start_s"]),
                end_s=None if i.get("end_s") is None else float(i["end_s"]),
                kind=str(i.get("kind", "closure")),
                speed_factor=float(i.get("speed_factor", 1.0)),
            )
            for i in data.get("incidents") or []
        ]
        emergencies = [
            EmergencyRequest(
                id=str(e["id"]),
                origin=str(e["origin"]),
                destination=str(e["destination"]),
                release_s=float(e["release_s"]),
                vehicle_class=str(e.get("vehicle_class", "ambulance")),
            )
            for e in data.get("emergencies") or []
        ]
    except (KeyError, TypeError) as exc:
        raise ScenarioError(f"Missing or invalid scenario field: {exc}") from exc
    scenario = Scenario(
        id=str(data.get("id", "unnamed")),
        description=str(data.get("description", "")),
        network=network,
        demand=demand,
        incidents=incidents,
        emergencies=emergencies,
        route_noise=float(data.get("route_noise", 0.2)),
        source_path=source_path,
        sha256=sha256,
    )
    validate_scenario(scenario)
    return scenario


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path)
    raw = path.read_bytes()
    data = yaml.safe_load(raw) or {}
    return scenario_from_dict(data, str(path), hashlib.sha256(raw).hexdigest())


def validate_scenario(scenario: Scenario) -> None:
    net = scenario.network
    cost = free_flow_cost(net)
    if scenario.route_noise < 0:
        raise ScenarioError("route_noise must be non-negative")
    for flow in scenario.demand:
        for node in (flow.origin, flow.destination):
            if node not in net.nodes:
                raise ScenarioError(f"Demand references unknown node {node}")
        if flow.end_s is not None and flow.end_s <= flow.start_s:
            raise ScenarioError(f"Demand {flow.origin}->{flow.destination}: end_s must exceed start_s")
        if shortest_path(net, flow.origin, flow.destination, cost) is None:
            raise ScenarioError(f"No route from {flow.origin} to {flow.destination}")
    seen: set[str] = set()
    for inc in scenario.incidents:
        if inc.id in seen:
            raise ScenarioError(f"Duplicate incident id {inc.id}")
        seen.add(inc.id)
        if inc.kind not in INCIDENT_KINDS:
            raise ScenarioError(f"Incident {inc.id}: kind must be one of {list(INCIDENT_KINDS)}")
        if not inc.edges:
            raise ScenarioError(f"Incident {inc.id} must list at least one edge")
        for eid in inc.edges:
            if eid not in net.edges:
                raise ScenarioError(f"Incident {inc.id} references unknown edge {eid}")
        if inc.kind == "slowdown" and not 0 < inc.speed_factor <= 1:
            raise ScenarioError(f"Incident {inc.id}: speed_factor must be in (0, 1]")
        if inc.end_s is not None and inc.end_s <= inc.start_s:
            raise ScenarioError(f"Incident {inc.id}: end_s must exceed start_s")
    seen.clear()
    for req in scenario.emergencies:
        if req.id in seen:
            raise ScenarioError(f"Duplicate emergency id {req.id}")
        seen.add(req.id)
        for node in (req.origin, req.destination):
            if node not in net.nodes:
                raise ScenarioError(f"Emergency {req.id} references unknown node {node}")
        if shortest_path(net, req.origin, req.destination, cost) is None:
            raise ScenarioError(f"Emergency {req.id}: no route from {req.origin} to {req.destination}")


def generate_departures(scenario: Scenario, duration_s: float, rng: random.Random) -> list[Departure]:
    """Sample Poisson departures for every demand flow, sorted by departure time."""
    raw: list[tuple[float, str, str]] = []
    for flow in scenario.demand:
        if flow.vehicles_per_hour <= 0:
            continue
        rate = flow.vehicles_per_hour / 3600.0
        end = min(duration_s, flow.end_s if flow.end_s is not None else duration_s)
        t = flow.start_s + rng.expovariate(rate)
        while t < end:
            raw.append((t, flow.origin, flow.destination))
            t += rng.expovariate(rate)
    raw.sort()
    return [Departure(f"veh_{i:05d}", t, o, d) for i, (t, o, d) in enumerate(raw)]
