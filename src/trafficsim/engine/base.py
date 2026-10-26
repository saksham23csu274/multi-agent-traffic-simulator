"""Engine-agnostic interface that the orchestrator and agents depend on."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from ..models import ActionResult, EdgeState, IntersectionObservation, SignalAction, StepResult
from ..network import RoadNetwork
from ..scenario import Incident

EventSink = Callable[..., None]


class EngineError(RuntimeError):
    """Raised for invalid engine usage (unknown vehicle, engine not started, ...)."""


class TrafficEngine(ABC):
    """Adapter boundary between the project and a concrete traffic simulator."""

    name: str = "abstract"

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def step(self) -> StepResult: ...

    @property
    @abstractmethod
    def time_s(self) -> float: ...

    @abstractmethod
    def get_network_graph(self) -> RoadNetwork: ...

    @abstractmethod
    def get_intersection_state(self, intersection_id: str) -> IntersectionObservation: ...

    @abstractmethod
    def set_signal_action(self, intersection_id: str, action: SignalAction) -> ActionResult: ...

    @abstractmethod
    def add_vehicle(self, vehicle_id: str, route: list[str], vehicle_class: str, depart_s: float,
                    origin: str, destination: str) -> None: ...

    @abstractmethod
    def reroute_vehicle(self, vehicle_id: str, remaining_route: list[str]) -> bool: ...

    @abstractmethod
    def apply_incident(self, incident: Incident) -> ActionResult: ...

    @abstractmethod
    def clear_incident(self, incident: Incident) -> ActionResult: ...

    @abstractmethod
    def edge_state(self, edge_id: str) -> EdgeState: ...

    @abstractmethod
    def closed_edges(self) -> frozenset[str]: ...

    @abstractmethod
    def vehicle_info(self, vehicle_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def remaining_route_etas(self, vehicle_id: str) -> list[tuple[str, float]]: ...

    @abstractmethod
    def counts(self) -> dict[str, int]: ...

    @abstractmethod
    def snapshot(self) -> dict[str, Any]: ...

    def close(self) -> None:  # pragma: no cover - nothing to release by default
        pass
