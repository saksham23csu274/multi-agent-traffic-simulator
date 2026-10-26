"""Run configuration: loading, defaults, and validation."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SIGNAL_STRATEGIES = ("fixed_time", "adaptive_queue", "max_pressure")
ROUTING_STRATEGIES = ("static_shortest_path", "dynamic_shortest_path")
ENGINES = ("meso",)

# Lower bounds that a run configuration must respect before a run may start.
SAFETY_LIMITS = {
    "min_green_s": 5.0,
    "yellow_s": 3.0,
    "all_red_s": 1.0,
}


class ConfigError(ValueError):
    """Raised when a run configuration is invalid."""


@dataclass
class SimulationConfig:
    engine: str = "meso"
    step_length_s: float = 1.0
    duration_s: float = 1800.0
    decision_interval_s: float = 5.0
    saturation_flow_vps_per_lane: float = 0.5
    jam_spacing_m: float = 7.5
    timeout_s: float | None = None


@dataclass
class TrafficControlConfig:
    strategy: str = "adaptive_queue"
    min_green_s: float = 8.0
    max_green_s: float = 45.0
    yellow_s: float = 3.0
    all_red_s: float = 1.0
    fixed_green_s: float = 25.0
    hysteresis: float = 0.2
    wait_weight: float = 0.1


@dataclass
class EmergencyConfig:
    enabled: bool = True
    routing_strategy: str = "dynamic_shortest_path"
    priority_enabled: bool = True
    reroute_threshold_percent: float = 15.0
    reroute_interval_s: float = 10.0
    priority_horizon_s: float = 30.0
    max_priority_hold_s: float = 30.0
    fairness_window_s: float = 300.0
    max_priority_share: float = 0.5
    queue_jump: bool = True


@dataclass
class MonitoringConfig:
    congestion_threshold: float = 0.8
    clear_threshold: float = 0.6


@dataclass
class MetricsConfig:
    sample_interval_s: float = 5.0


@dataclass
class OutputsConfig:
    directory: str = "runs"
    save_events: bool = True
    save_decisions: bool = True
    export_csv: bool = True
    html_report: bool = True


@dataclass
class RunConfig:
    scenario: str
    label: str | None = None
    random_seed: int = 42
    simulation: SimulationConfig = field(default_factory=SimulationConfig)
    traffic_control: TrafficControlConfig = field(default_factory=TrafficControlConfig)
    emergency: EmergencyConfig = field(default_factory=EmergencyConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    outputs: OutputsConfig = field(default_factory=OutputsConfig)
    source_path: str | None = None

    @property
    def display_label(self) -> str:
        if self.label:
            return self.label
        priority = "priority" if self.emergency.enabled and self.emergency.priority_enabled else "no-priority"
        return f"{self.traffic_control.strategy}/{priority}"

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data.pop("source_path", None)
        return data


_SECTIONS = {
    "simulation": SimulationConfig,
    "traffic_control": TrafficControlConfig,
    "emergency": EmergencyConfig,
    "monitoring": MonitoringConfig,
    "metrics": MetricsConfig,
    "outputs": OutputsConfig,
}


def _build_section(cls: type, data: Any, name: str) -> Any:
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ConfigError(f"Section '{name}' must be a mapping")
    names = {f.name for f in dataclasses.fields(cls)}
    unknown = set(data) - names
    if unknown:
        raise ConfigError(f"Unknown key(s) in '{name}': {sorted(unknown)}")
    return cls(**data)


def config_from_dict(data: dict[str, Any], base_dir: Path | None = None) -> RunConfig:
    if not isinstance(data, dict):
        raise ConfigError("Run configuration must be a mapping")
    top_level = {"scenario", "label", "random_seed", *_SECTIONS}
    unknown = set(data) - top_level
    if unknown:
        raise ConfigError(f"Unknown top-level key(s): {sorted(unknown)}")
    if "scenario" not in data:
        raise ConfigError("Missing required key 'scenario' (path to a scenario YAML file)")
    scenario = Path(str(data["scenario"]))
    if not scenario.is_absolute() and base_dir is not None:
        scenario = (base_dir / scenario).resolve()
    config = RunConfig(
        scenario=str(scenario),
        label=data.get("label"),
        random_seed=data.get("random_seed", 42),
        **{name: _build_section(cls, data.get(name), name) for name, cls in _SECTIONS.items()},
    )
    validate_config(config)
    return config


def load_run_config(path: str | Path, overrides: dict[str, Any] | None = None) -> RunConfig:
    """Load a YAML run configuration. Relative scenario paths resolve against the file's folder.

    ``overrides`` uses dotted keys, e.g. ``{"traffic_control.strategy": "fixed_time"}``.
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    for dotted, value in (overrides or {}).items():
        target = data
        *parents, leaf = dotted.split(".")
        for key in parents:
            target = target.setdefault(key, {})
        target[leaf] = value
    config = config_from_dict(data, base_dir=path.resolve().parent)
    config.source_path = str(path)
    return config


def _require_number(value: Any, name: str, minimum: float | None = None, exclusive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be a number, got {value!r}")
    if minimum is not None:
        if exclusive and value <= minimum:
            raise ConfigError(f"{name} must be greater than {minimum}, got {value}")
        if not exclusive and value < minimum:
            raise ConfigError(f"{name} must be at least {minimum}, got {value}")


def validate_config(config: RunConfig) -> None:
    """Reject invalid values, unknown strategies, missing files, and unsafe signal timing."""
    if not isinstance(config.random_seed, int) or isinstance(config.random_seed, bool):
        raise ConfigError(f"random_seed must be an integer, got {config.random_seed!r}")
    if not Path(config.scenario).is_file():
        raise ConfigError(f"Scenario file not found: {config.scenario}")

    sim = config.simulation
    if sim.engine not in ENGINES:
        raise ConfigError(f"Unknown engine {sim.engine!r}; supported: {list(ENGINES)}")
    _require_number(sim.step_length_s, "simulation.step_length_s", 0, exclusive=True)
    _require_number(sim.duration_s, "simulation.duration_s", 0, exclusive=True)
    _require_number(sim.decision_interval_s, "simulation.decision_interval_s", sim.step_length_s)
    _require_number(sim.saturation_flow_vps_per_lane, "simulation.saturation_flow_vps_per_lane", 0, exclusive=True)
    _require_number(sim.jam_spacing_m, "simulation.jam_spacing_m", 0, exclusive=True)
    if sim.timeout_s is not None:
        _require_number(sim.timeout_s, "simulation.timeout_s", 0, exclusive=True)

    tc = config.traffic_control
    if tc.strategy not in SIGNAL_STRATEGIES:
        raise ConfigError(f"Unknown traffic_control.strategy {tc.strategy!r}; supported: {list(SIGNAL_STRATEGIES)}")
    for key, minimum in SAFETY_LIMITS.items():
        _require_number(getattr(tc, key), f"traffic_control.{key}", minimum)
    _require_number(tc.max_green_s, "traffic_control.max_green_s", tc.min_green_s, exclusive=True)
    _require_number(tc.fixed_green_s, "traffic_control.fixed_green_s", tc.min_green_s)
    if tc.fixed_green_s > tc.max_green_s:
        raise ConfigError("traffic_control.fixed_green_s must not exceed max_green_s")
    _require_number(tc.hysteresis, "traffic_control.hysteresis", 0)
    _require_number(tc.wait_weight, "traffic_control.wait_weight", 0)

    em = config.emergency
    if em.routing_strategy not in ROUTING_STRATEGIES:
        raise ConfigError(
            f"Unknown emergency.routing_strategy {em.routing_strategy!r}; supported: {list(ROUTING_STRATEGIES)}"
        )
    _require_number(em.reroute_threshold_percent, "emergency.reroute_threshold_percent", 0)
    if em.reroute_threshold_percent >= 100:
        raise ConfigError("emergency.reroute_threshold_percent must be below 100")
    _require_number(em.reroute_interval_s, "emergency.reroute_interval_s", sim.step_length_s)
    _require_number(em.priority_horizon_s, "emergency.priority_horizon_s", 0, exclusive=True)
    _require_number(em.max_priority_hold_s, "emergency.max_priority_hold_s", 0)
    _require_number(em.fairness_window_s, "emergency.fairness_window_s", 0, exclusive=True)
    _require_number(em.max_priority_share, "emergency.max_priority_share", 0, exclusive=True)
    if em.max_priority_share > 1:
        raise ConfigError("emergency.max_priority_share must be at most 1")

    mon = config.monitoring
    _require_number(mon.congestion_threshold, "monitoring.congestion_threshold", 0, exclusive=True)
    _require_number(mon.clear_threshold, "monitoring.clear_threshold", 0)
    if not mon.clear_threshold < mon.congestion_threshold <= 1:
        raise ConfigError("monitoring thresholds must satisfy clear_threshold < congestion_threshold <= 1")

    _require_number(config.metrics.sample_interval_s, "metrics.sample_interval_s", sim.step_length_s)
