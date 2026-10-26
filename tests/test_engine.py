from trafficsim.engine import MesoEngine
from trafficsim.models import ALL_RED, GREEN, HOLD, PASSENGER, REQUEST_PHASE, YELLOW, SignalAction
from trafficsim.network import build_grid
from trafficsim.scenario import Incident

ROUTE_EW = ["B_W_0->J_0_0", "J_0_0->J_0_1", "J_0_1->B_E_0"]


def run(engine, seconds):
    done = []
    for _ in range(seconds):
        done.extend(engine.step().completed)
    return done


def switch(engine, node, phase):
    return engine.set_signal_action(node, SignalAction("test", node, REQUEST_PHASE, phase))


def test_red_signal_holds_queue_and_green_releases(engine):
    # Both junctions start on NS, so the eastbound vehicle must stop at J_0_0.
    engine.add_vehicle("v1", ROUTE_EW, PASSENGER, 0, "B_W_0", "B_E_0")
    run(engine, 15)
    assert engine.vehicle_info("v1")["state"] == "queued"
    assert engine.edge_state("B_W_0->J_0_0").queue == 1
    assert switch(engine, "J_0_0", "EW").accepted
    switch(engine, "J_0_1", "EW")
    trips = run(engine, 60)
    assert [t.vehicle_id for t in trips] == ["v1"]
    assert trips[0].waiting_time_s > 0
    assert trips[0].stops == 1


def test_signal_transition_passes_through_yellow_and_all_red(engine):
    assert switch(engine, "J_0_0", "EW").reason == "transition_started"
    stages = []
    for _ in range(5):
        engine.step()
        obs = engine.get_intersection_state("J_0_0")
        stages.append((obs.stage, obs.current_phase))
    assert stages[0] == (YELLOW, "NS")
    assert stages[2] == (ALL_RED, "NS")
    assert stages[3] == (GREEN, "EW")
    # Commands during a transition are refused by the engine.
    switch(engine, "J_0_1", "EW")
    engine.step()
    assert not switch(engine, "J_0_1", "NS").accepted


def test_engine_rejects_unknown_phase_and_intersection(engine):
    assert switch(engine, "J_0_0", "XX").reason == "unknown_phase"
    assert not engine.set_signal_action("B_W_0", SignalAction("t", "B_W_0", HOLD)).accepted


def test_saturation_flow_limits_discharge(engine):
    switch(engine, "J_0_0", "EW")  # northbound approach is red while the queue builds
    for i in range(6):
        engine.add_vehicle(f"v{i}", ["B_S_0->J_0_0", "J_0_0->J_1_0", "J_1_0->B_N_0"], PASSENGER, 0, "B_S_0", "B_N_0")
    run(engine, 60)
    assert engine.edge_state("B_S_0->J_0_0").queue == 6
    switch(engine, "J_0_0", "NS")
    run(engine, 4)  # yellow + all-red: nothing moves
    assert engine.edge_state("B_S_0->J_0_0").queue == 6
    run(engine, 4)  # 0.5 veh/s -> two vehicles in four seconds of green
    assert engine.edge_state("B_S_0->J_0_0").queue == 4


def test_spillback_blocks_full_downstream_edge():
    net = build_grid(1, 2, block_length_m=15, speed_limit_mps=10)  # storage capacity 2 per edge
    eng = MesoEngine(net, step_length_s=1)
    eng.start()
    eng.capacity["J_0_0->J_0_1"] = 1
    for i in range(3):
        eng.add_vehicle(f"v{i}", ["B_W_0->J_0_0", "J_0_0->J_0_1", "J_0_1->B_E_0"], PASSENGER, i * 0.5, "B_W_0", "B_E_0")
    switch(eng, "J_0_0", "EW")
    run(eng, 10)
    assert eng.edge_state("J_0_0->J_0_1").occupancy <= 1


def test_closure_reroutes_queued_vehicle(engine):
    engine.add_vehicle("v1", ROUTE_EW, PASSENGER, 0, "B_W_0", "B_E_0")
    closure = Incident("c", ("J_0_0->J_0_1",), 0)
    engine.apply_incident(closure)
    for i in range(10):  # alternate every signal so the detour can be completed
        for node in engine.network.signalized_nodes:
            switch(engine, node, "EW" if i % 2 == 0 else "NS")
        run(engine, 20)
    info = engine.vehicle_info("v1")
    assert info["state"] == "arrived"
    assert "J_0_0->J_0_1" not in info["route"]
    assert info["route_changes"] == 1
    assert engine.clear_incident(closure).accepted


def test_emergency_vehicle_jumps_queue(engine):
    for i in range(3):
        engine.add_vehicle(f"v{i}", ROUTE_EW, PASSENGER, 0, "B_W_0", "B_E_0")
    engine.add_vehicle("ems", ROUTE_EW, "emergency", 0, "B_W_0", "B_E_0")
    run(engine, 15)
    queue = engine._edges["B_W_0->J_0_0"].queue
    assert queue[0] == "ems"


def test_remaining_route_etas_are_increasing(engine):
    engine.add_vehicle("ems", ROUTE_EW, "emergency", 0, "B_W_0", "B_E_0")
    engine.step()
    etas = engine.remaining_route_etas("ems")
    assert [e for e, _ in etas] == ROUTE_EW
    assert all(a[1] < b[1] for a, b in zip(etas, etas[1:]))
