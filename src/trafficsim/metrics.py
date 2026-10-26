"""Metric collection and run-level aggregation.

Units: seconds for times, metres for distances, vehicles for queues, vehicles/hour for throughput.
Trip-based metrics (travel time, waiting, time loss, stops) cover completed passenger trips only;
vehicles still in the network or waiting to enter at the end of a run are reported as unfinished.
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

from .models import EMERGENCY, TripRecord
from .scenario import Incident

RECOVERY_BASELINE_WINDOW_S = 300.0
THROUGHPUT_WINDOW_S = 60.0


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


class MetricsCollector:
    def __init__(self, sample_interval_s: float):
        self.sample_interval_s = sample_interval_s
        self.trips: list[TripRecord] = []
        self.timeseries: list[dict[str, Any]] = []
        self.frames: list[dict[str, Any]] = []
        self.decisions = 0
        self.decision_latency_ms: list[float] = []
        self.rejections: Counter[str] = Counter()
        self.agent_faults = 0
        self.fallback_decisions = 0
        self.agents_replaced = 0
        self.forced_phase_changes = 0
        self.engine_rejections = 0

    def record_trips(self, trips: list[TripRecord]) -> None:
        self.trips.extend(trips)

    def record_decision(self, latency_ms: float, accepted: bool, reason: str) -> None:
        self.decisions += 1
        self.decision_latency_ms.append(latency_ms)
        if not accepted:
            self.rejections[reason] += 1

    def sample(self, t: float, counts: dict[str, int], max_edge_queue: int, mean_occupancy: float,
               congested_edges: int, active_emergencies: int, frame: dict[str, Any]) -> None:
        passenger = [trip for trip in self.trips if trip.vehicle_class != EMERGENCY]
        window = min(THROUGHPUT_WINDOW_S, t)
        recent = sum(1 for trip in passenger if trip.arrival_s > t - window)
        self.timeseries.append({
            "time_s": round(t, 3),
            "vehicles_in_network": counts["in_network"],
            "queued_vehicles": counts["queued"],
            "waiting_to_insert": counts["waiting_to_insert"],
            "completed_trips": len(passenger),
            "throughput_vph": round(recent * 3600.0 / window, 1) if window > 0 else 0.0,
            "max_edge_queue": max_edge_queue,
            "mean_occupancy_ratio": round(mean_occupancy, 4),
            "congested_edges": congested_edges,
            "active_emergencies": active_emergencies,
        })
        self.frames.append(frame)

    def incident_recovery(self, incidents: list[Incident]) -> list[dict[str, Any]]:
        results = []
        for inc in incidents:
            before = [r["queued_vehicles"] for r in self.timeseries
                      if inc.start_s - RECOVERY_BASELINE_WINDOW_S <= r["time_s"] < inc.start_s]
            baseline = statistics.fmean(before) if before else 0.0
            during = [r["queued_vehicles"] for r in self.timeseries
                      if inc.start_s <= r["time_s"] <= (inc.end_s if inc.end_s is not None else float("inf"))]
            recovery = None
            if inc.end_s is not None:
                for r in self.timeseries:
                    if r["time_s"] >= inc.end_s and r["queued_vehicles"] <= baseline * 1.1 + 1:
                        recovery = round(r["time_s"] - inc.end_s, 1)
                        break
            results.append({
                "incident_id": inc.id,
                "kind": inc.kind,
                "baseline_queued_vehicles": round(baseline, 2),
                "peak_queued_vehicles": max(during) if during else None,
                "recovery_time_s": recovery,
            })
        return results

    def summary(self, *, counts: dict[str, int], duration_s: float, congested_edge_seconds: float,
                emergency_records: list[dict[str, Any]], priority_stats: dict[str, int],
                incidents: list[Incident], wall_clock_s: float, steps: int) -> dict[str, Any]:
        passenger = [t for t in self.trips if t.vehicle_class != EMERGENCY]
        unfinished = counts["in_network"] + counts["waiting_to_insert"]
        unfinished -= sum(1 for r in emergency_records if r["status"] == "dispatched")
        queue_samples = [r["queued_vehicles"] for r in self.timeseries]
        travel = [t.travel_time_s for t in passenger]
        arrived = [r for r in emergency_records if r["status"] == "arrived"]
        latency = self.decision_latency_ms
        return {
            "traffic": {
                "trips_completed": len(passenger),
                "trips_unfinished": unfinished,
                "mean_travel_time_s": _mean(travel),
                "median_travel_time_s": _median(travel),
                "mean_waiting_time_s": _mean([t.waiting_time_s for t in passenger]),
                "mean_time_loss_s": _mean([t.time_loss_s for t in passenger]),
                "mean_depart_delay_s": _mean([t.depart_delay_s for t in passenger]),
                "mean_stops": _mean([float(t.stops) for t in passenger]),
                "mean_queued_vehicles": _mean([float(q) for q in queue_samples]),
                "max_queued_vehicles": max(queue_samples) if queue_samples else None,
                "max_edge_queue": max((r["max_edge_queue"] for r in self.timeseries), default=None),
                "throughput_vph": round(len(passenger) * 3600.0 / duration_s, 1),
                "congested_edge_seconds": round(congested_edge_seconds, 1),
            },
            "emergency": {
                "requests": len(emergency_records),
                "arrived": len(arrived),
                "mean_response_time_s": _mean([r["response_time_s"] for r in arrived]),
                "max_response_time_s": max((r["response_time_s"] for r in arrived), default=None),
                "mean_stopped_time_s": _mean([r["stopped_time_s"] for r in arrived]),
                "total_route_changes": sum(r["route_changes"] for r in emergency_records),
                "vehicles": emergency_records,
                **priority_stats,
            },
            "incidents": self.incident_recovery(incidents),
            "system": {
                "wall_clock_s": round(wall_clock_s, 3),
                "steps": steps,
                "steps_per_second": round(steps / wall_clock_s, 1) if wall_clock_s > 0 else None,
                "agent_decisions": self.decisions,
                "mean_decision_latency_ms": _mean(latency),
                "max_decision_latency_ms": round(max(latency), 3) if latency else None,
                "rejected_actions": sum(self.rejections.values()),
                "rejections_by_reason": dict(sorted(self.rejections.items())),
                "engine_rejections": self.engine_rejections,
                "forced_phase_changes": self.forced_phase_changes,
                "agent_faults": self.agent_faults,
                "fallback_decisions": self.fallback_decisions,
                "agents_replaced_by_fallback": self.agents_replaced,
            },
        }
