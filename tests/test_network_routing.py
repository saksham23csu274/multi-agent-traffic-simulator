from trafficsim.network import build_grid
from trafficsim.routing import free_flow_cost, shortest_path


def test_grid_structure():
    net = build_grid(3, 3)
    assert len(net.signalized_nodes) == 9
    assert len(net.nodes) == 9 + 12
    # 12 internal links + 12 boundary links, each two-way
    assert len(net.edges) == 48


def test_approaches_and_phases(grid):
    assert grid.approach("B_W_0->J_0_0") == "W"
    assert grid.approach("J_1_0->J_0_0") == "N"
    assert grid.approach("B_S_0->J_0_0") == "S"
    assert grid.approach("J_0_1->J_0_0") == "E"
    assert [p.id for p in grid.phases("J_0_0")] == ["NS", "EW"]
    assert grid.phase_for_edge("B_W_0->J_0_0") == "EW"
    assert grid.phase_for_edge("B_S_0->J_0_0") == "NS"
    assert grid.reverse_edge("B_W_0->J_0_0") == "J_0_0->B_W_0"


def test_shortest_path_straight_line(grid):
    path, cost = shortest_path(grid, "B_W_0", "B_E_0", free_flow_cost(grid))
    assert path == ["B_W_0->J_0_0", "J_0_0->J_0_1", "J_0_1->B_E_0"]
    assert cost == 30.0


def test_shortest_path_avoids_blocked_edges(grid):
    path, _ = shortest_path(grid, "B_W_0", "B_E_0", free_flow_cost(grid), blocked={"J_0_0->J_0_1"})
    assert "J_0_0->J_0_1" not in path
    assert path[0] == "B_W_0->J_0_0" and path[-1] == "J_0_1->B_E_0"


def test_shortest_path_unreachable(grid):
    blocked = set(grid.out_edges["B_W_0"])
    assert shortest_path(grid, "B_W_0", "B_E_0", free_flow_cost(grid), blocked=blocked) is None
