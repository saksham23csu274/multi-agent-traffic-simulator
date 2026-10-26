"""End-to-end scenario tests through the orchestrator."""

import json

import pytest

from trafficsim.agents import AdaptiveQueueAgent
from trafficsim.cli import main
from trafficsim.experiments import compare
from trafficsim.orchestrator import Orchestrator, run_simulation

from .conftest import make_config


def run(config, **kwargs):
    return Orchestrator(config, **kwargs).run()


def test_sample_run_completes_and_emergencies_arrive():
    result = run(make_config())
    s = result.summary
    assert result.status == "completed"
    assert s["traffic"]["trips_completed"] > 100
    assert s["emergency"]["arrived"] == 2
    assert s["emergency"]["priority_requests"] > 0
    assert s["emergency"]["priority_approved"] > 0
    types = {e["type"] for e in result.events}
    assert {"incident_start", "incident_end", "emergency_dispatched", "emergency_arrived",
            "priority_requested", "priority_cleared"} <= types


def test_closure_triggers_emergency_reroute():
    result = run(make_config())
    reroutes = [e for e in result.events if e["type"] == "emergency_rerouted" and e["vehicle_id"] == "EMS_1"]
    assert reroutes and reroutes[0]["reason"] == "route_blocked"
    ems1 = next(v for v in result.summary["emergency"]["vehicles"] if v["id"] == "EMS_1")
    assert ems1["route_changes"] >= 1


def test_runs_are_reproducible():
    a = run(make_config(random_seed=5)).summary
    b = run(make_config(random_seed=5)).summary
    c = run(make_config(random_seed=6)).summary
    for section in ("traffic", "emergency", "incidents"):
        assert a[section] == b[section]
    assert a["traffic"] != c["traffic"]


def test_priority_reduces_emergency_stopped_time():
    common = {"traffic_control": {"strategy": "fixed_time"}, "random_seed": 1}
    with_priority = run(make_config(**common)).summary["emergency"]
    without = run(make_config(emergency={"priority_enabled": False}, **common)).summary["emergency"]
    assert without["priority_requests"] == 0
    assert with_priority["mean_stopped_time_s"] < without["mean_stopped_time_s"]


def test_low_demand_scenario_has_no_unfinished_emergencies():
    result = run(make_config("scenarios/grid_low_demand.yaml", simulation={"duration_s": 900}))
    assert result.summary["emergency"]["arrived"] == 1
    assert result.summary["incidents"] == []


def test_multi_emergency_fairness_scenario():
    result = run(make_config("scenarios/grid_multi_emergency.yaml", simulation={"duration_s": 1500}))
    em = result.summary["emergency"]
    assert em["arrived"] == 5
    assert em["priority_requests"] >= em["priority_approved"] > 0


def test_custom_corridor_network_runs():
    result = run(make_config("scenarios/corridor.yaml", simulation={"duration_s": 900}))
    assert result.status == "completed"
    assert result.summary["emergency"]["arrived"] == 1


class CrashingAgent(AdaptiveQueueAgent):
    def decide(self, obs):
        raise RuntimeError("boom")


class MalformedAgent(AdaptiveQueueAgent):
    def decide(self, obs):
        return {"action": "hold"}


@pytest.mark.parametrize("bad_agent", [CrashingAgent, MalformedAgent])
def test_faulty_agent_falls_back_without_stopping_run(bad_agent):
    def factory(node, config):
        cls = bad_agent if node == "J_1_1" else AdaptiveQueueAgent
        return cls(node, config.traffic_control, priority_enabled=True)

    result = run(make_config(simulation={"duration_s": 600}), agent_factory=factory)
    sysm = result.summary["system"]
    assert result.status == "completed"
    assert sysm["agent_faults"] >= 3
    assert sysm["agents_replaced_by_fallback"] == 1
    assert any(e["type"] == "agent_replaced_by_fallback" for e in result.events)


def test_outputs_written(tmp_path):
    config = make_config(simulation={"duration_s": 300}, outputs={"html_report": True})
    result = run_simulation(config, tmp_path)
    out = result.output_dir
    for name in ("manifest.json", "summary.json", "events.jsonl", "decisions.jsonl", "timeseries.csv",
                 "trips.csv", "report.html"):
        assert (out / name).is_file(), name
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["random_seed"] == 42 and manifest["scenario"]["sha256"]
    assert "<svg" in (out / "report.html").read_text()


def test_compare_and_cli(tmp_path, root):
    out = compare([root / "configs" / "baseline_fixed_time.yaml", root / "configs" / "adaptive_queue.yaml"],
                  [1, 2], tmp_path / "cmp", log=lambda _: None)
    data = json.loads((out / "comparison.json").read_text())
    assert len(data["runs"]) == 4
    assert data["aggregate"]["fixed-time (baseline)"]["traffic.mean_travel_time_s"]["n"] == 2
    assert (out / "comparison.html").is_file()
    assert main(["validate", "--config", str(root / "configs" / "adaptive_queue.yaml")]) == 0
    assert main(["run", "--config", str(root / "configs" / "adaptive_queue.yaml"), "--duration", "120",
                 "--output", str(tmp_path / "runs")]) == 0
    assert main(["run", "--config", str(tmp_path / "missing.yaml")]) == 2
