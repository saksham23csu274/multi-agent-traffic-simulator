import random

import pytest
import yaml

from trafficsim.config import ConfigError, load_run_config
from trafficsim.scenario import ScenarioError, generate_departures, load_scenario, scenario_from_dict

from .conftest import make_config


@pytest.mark.parametrize("name", ["baseline_fixed_time", "fixed_time_priority", "adaptive_queue", "max_pressure"])
def test_shipped_configs_load(root, name):
    config = load_run_config(root / "configs" / f"{name}.yaml")
    assert config.scenario.endswith("sample_grid.yaml")


@pytest.mark.parametrize("name", ["sample_grid", "grid_low_demand", "grid_multi_emergency", "corridor"])
def test_shipped_scenarios_load(root, name):
    scenario = load_scenario(root / "scenarios" / f"{name}.yaml")
    assert scenario.id == name
    assert scenario.sha256


def test_overrides_apply(root):
    config = load_run_config(root / "configs" / "adaptive_queue.yaml",
                             {"traffic_control.strategy": "max_pressure", "random_seed": 7})
    assert config.traffic_control.strategy == "max_pressure"
    assert config.random_seed == 7


@pytest.mark.parametrize(
    "sections, message",
    [
        ({"traffic_control": {"strategy": "magic"}}, "Unknown traffic_control.strategy"),
        ({"traffic_control": {"yellow_s": 2}}, "yellow_s must be at least 3"),
        ({"traffic_control": {"all_red_s": 0}}, "all_red_s must be at least 1"),
        ({"traffic_control": {"min_green_s": 10, "max_green_s": 10}}, "max_green_s must be greater"),
        ({"simulation": {"decision_interval_s": 0.5}}, "decision_interval_s must be at least"),
        ({"simulation": {"engine": "sumo"}}, "Unknown engine"),
        ({"emergency": {"routing_strategy": "teleport"}}, "routing_strategy"),
        ({"emergency": {"max_priority_share": 1.5}}, "max_priority_share"),
        ({"traffic_control": {"bogus": 1}}, "Unknown key"),
    ],
)
def test_invalid_configs_rejected(sections, message):
    with pytest.raises(ConfigError, match=message):
        make_config(**sections)


def test_missing_scenario_rejected(tmp_path):
    path = tmp_path / "run.yaml"
    path.write_text(yaml.safe_dump({"scenario": "nope.yaml"}))
    with pytest.raises(ConfigError, match="Scenario file not found"):
        load_run_config(path)


def test_scenario_rejects_unknown_incident_edge():
    with pytest.raises(ScenarioError, match="unknown edge"):
        scenario_from_dict({
            "network": {"type": "grid", "rows": 1, "cols": 1},
            "incidents": [{"id": "x", "edges": ["nope"], "start_s": 0}],
        })


def test_scenario_rejects_impossible_route():
    with pytest.raises(ScenarioError, match="No route"):
        scenario_from_dict({
            "network": {"type": "custom", "nodes": [
                {"id": "A", "x": 0, "y": 0, "signalized": False},
                {"id": "B", "x": 100, "y": 0, "signalized": False},
            ], "edges": [{"from": "A", "to": "B", "bidirectional": False}]},
            "demand": [{"origin": "B", "destination": "A", "vehicles_per_hour": 10}],
        })


def test_departures_are_reproducible(root):
    scenario = load_scenario(root / "scenarios" / "sample_grid.yaml")
    a = generate_departures(scenario, 1800, random.Random(3))
    b = generate_departures(scenario, 1800, random.Random(3))
    c = generate_departures(scenario, 1800, random.Random(4))
    assert a == b
    assert a != c
    assert all(x.depart_s <= y.depart_s for x, y in zip(a, a[1:]))
