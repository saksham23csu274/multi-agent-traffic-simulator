"""Typed, versioned observation, action, and message schemas shared by all components."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1

GREEN, YELLOW, ALL_RED = "green", "yellow", "all_red"
HOLD, REQUEST_PHASE = "hold", "request_phase"
ACTION_TYPES = (HOLD, REQUEST_PHASE)
REASON_EMERGENCY = "emergency_vehicle_approaching"
PASSENGER, EMERGENCY = "passenger", "emergency"


@dataclass(frozen=True)
class MovementObservation:
    id: str
    approach: str
    phase_id: str | None
    queue_vehicles: int
    mean_wait_s: float
    approaching_vehicles: int
    downstream_queue: float
    downstream_blocked: bool


@dataclass(frozen=True)
class PriorityRequest:
    request_id: str
    vehicle_id: str
    intersection_id: str
    movement_id: str
    phase_id: str
    eta_s: float
    issued_s: float
    expires_s: float


@dataclass(frozen=True)
class IntersectionObservation:
    simulation_time_s: float
    intersection_id: str
    current_phase: str
    stage: str
    phase_elapsed_s: float
    valid_phases: tuple[str, ...]
    movements: tuple[MovementObservation, ...]
    emergency_requests: tuple[PriorityRequest, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def queue_by_phase(self) -> dict[str, int]:
        totals = {p: 0 for p in self.valid_phases}
        for m in self.movements:
            if m.phase_id in totals:
                totals[m.phase_id] += m.queue_vehicles
        return totals


@dataclass(frozen=True)
class SignalAction:
    agent_id: str
    intersection_id: str
    action: str
    phase_id: str | None = None
    requested_duration_s: float | None = None
    reason_code: str = "policy"
    request_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionResult:
    accepted: bool
    reason: str


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    reason: str
    priority: bool = False


@dataclass(frozen=True)
class TripRecord:
    vehicle_id: str
    vehicle_class: str
    origin: str
    destination: str
    depart_s: float
    insert_s: float
    arrival_s: float
    travel_time_s: float
    waiting_time_s: float
    depart_delay_s: float
    stops: int
    route_length_m: float
    free_flow_time_s: float
    time_loss_s: float
    route_changes: int


@dataclass
class StepResult:
    time_s: float
    completed: list[TripRecord] = field(default_factory=list)


@dataclass(frozen=True)
class EdgeState:
    edge_id: str
    occupancy: int
    capacity: int
    queue: int
    moving: int
    speed_factor: float
    closed: bool

    @property
    def occupancy_ratio(self) -> float:
        return self.occupancy / self.capacity


@dataclass(frozen=True)
class Message:
    topic: str
    sender: str
    time_s: float
    payload: dict[str, Any]
    schema_version: int = SCHEMA_VERSION
