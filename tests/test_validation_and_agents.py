import pytest

from trafficsim.agents import AdaptiveQueueAgent, FixedTimeAgent, MaxPressureAgent
from trafficsim.config import EmergencyConfig, TrafficControlConfig
from trafficsim.models import (
    GREEN,
    HOLD,
    REASON_EMERGENCY,
    REQUEST_PHASE,
    YELLOW,
    IntersectionObservation,
    MovementObservation,
    PriorityRequest,
    SignalAction,
)
from trafficsim.validation import ActionValidator

TIMING = TrafficControlConfig(min_green_s=8, max_green_s=45, fixed_green_s=25)


def obs(phase="NS", elapsed=20.0, stage=GREEN, ns_queue=0, ew_queue=0, requests=(), down=0.0):
    movements = (
        MovementObservation("n", "N", "NS", ns_queue, 5.0, 0, down, False),
        MovementObservation("w", "W", "EW", ew_queue, 5.0, 0, down, False),
    )
    return IntersectionObservation(100.0, "J", phase, stage, elapsed, ("NS", "EW"), movements, tuple(requests))


def act(action, phase=None, reason="policy", request_id=None, node="J"):
    return SignalAction("agent", node, action, phase, reason_code=reason, request_id=request_id)


def request(phase="EW", rid="EMS@J"):
    return PriorityRequest(rid, "EMS", "J", "w", phase, 10.0, 90.0, 150.0)


@pytest.fixture
def validator():
    return ActionValidator(TIMING, EmergencyConfig(max_priority_hold_s=30, fairness_window_s=300, max_priority_share=0.5))


def test_min_green_enforced(validator):
    verdict = validator.validate(obs(elapsed=5), act(REQUEST_PHASE, "EW"))
    assert not verdict.accepted and verdict.reason == "min_green_not_met"
    assert validator.validate(obs(elapsed=8), act(REQUEST_PHASE, "EW")).accepted


def test_max_green_enforced_only_with_conflicting_demand(validator):
    assert validator.validate(obs(elapsed=50, ew_queue=0), act(HOLD)).accepted
    verdict = validator.validate(obs(elapsed=50, ew_queue=3), act(HOLD))
    assert not verdict.accepted and verdict.reason == "max_green_reached"


@pytest.mark.parametrize(
    "action, reason",
    [
        ("not an action", "malformed_action"),
        (act(HOLD, node="OTHER"), "wrong_intersection"),
        (act("explode"), "unknown_action"),
        (act(REQUEST_PHASE, "DIAGONAL"), "unknown_phase"),
    ],
)
def test_malformed_actions_rejected(validator, action, reason):
    assert validator.validate(obs(), action).reason == reason


def test_no_commands_during_transition(validator):
    assert validator.validate(obs(stage=YELLOW), act(HOLD)).reason == "transition_in_progress"


def test_priority_requires_eligible_request(validator):
    action = act(REQUEST_PHASE, "EW", REASON_EMERGENCY, "EMS@J")
    assert validator.validate(obs(), action, {}).reason == "priority_request_not_eligible"
    verdict = validator.validate(obs(), action, {"EMS@J": request()})
    assert verdict.accepted and verdict.priority
    mismatch = validator.validate(obs(), act(REQUEST_PHASE, "EW", REASON_EMERGENCY, "EMS@J"),
                                  {"EMS@J": request(phase="NS")})
    assert mismatch.reason == "priority_phase_mismatch"


def test_priority_hold_bounded_beyond_max_green(validator):
    eligible = {"EMS@J": request(phase="NS")}
    hold = act(HOLD, "NS", REASON_EMERGENCY, "EMS@J")
    assert validator.validate(obs(elapsed=60, ew_queue=5), hold, eligible).reason == "priority_hold"
    assert not validator.validate(obs(elapsed=76, ew_queue=5), hold, eligible).accepted
    _, denied = validator.screen_requests(obs(elapsed=76, ew_queue=5), [request(phase="NS")])
    assert denied[0][1] == "max_priority_hold_reached"


def test_fairness_budget(validator):
    for i in range(30):
        validator.record_priority("J", 90.0 - i, 5.0)  # 150 s of priority in the window
    eligible, denied = validator.screen_requests(obs(), [request()])
    assert not eligible and denied[0][1] == "fairness_budget_exhausted"


def test_fixed_time_agent_cycles():
    agent = FixedTimeAgent("J", TIMING)
    assert agent.decide(obs(elapsed=10)).action == HOLD
    action = agent.decide(obs(elapsed=25))
    assert (action.action, action.phase_id) == (REQUEST_PHASE, "EW")


def test_adaptive_agent_follows_demand():
    agent = AdaptiveQueueAgent("J", TIMING)
    assert agent.decide(obs(elapsed=5, ew_queue=10)).action == HOLD  # min green
    assert agent.decide(obs(elapsed=12, ns_queue=5, ew_queue=10)).phase_id == "EW"
    assert agent.decide(obs(elapsed=12, ns_queue=5, ew_queue=5)).action == HOLD  # hysteresis


def test_max_pressure_accounts_for_downstream():
    agent = MaxPressureAgent("J", TIMING)
    demand = agent.phase_demand(obs(ns_queue=4, ew_queue=6, down=5))
    assert demand == {"NS": 0.0, "EW": 1.0}


def test_agent_serves_priority_request_first():
    agent = AdaptiveQueueAgent("J", TIMING, priority_enabled=True)
    action = agent.decide(obs(elapsed=12, ns_queue=20, requests=[request()]))
    assert (action.action, action.phase_id, action.reason_code) == (REQUEST_PHASE, "EW", REASON_EMERGENCY)
    no_priority = AdaptiveQueueAgent("J", TIMING, priority_enabled=False)
    assert no_priority.decide(obs(elapsed=12, ns_queue=20, requests=[request()])).reason_code != REASON_EMERGENCY
