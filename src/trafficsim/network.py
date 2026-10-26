"""Road network model: nodes, directed edges, approaches, and signal phases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

DEFAULT_JAM_SPACING_M = 7.5

# Two-phase operation: each phase serves the approaches on one axis.
PHASE_APPROACHES = {"NS": ("N", "S"), "EW": ("E", "W")}


class NetworkError(ValueError):
    """Raised when a network definition is invalid."""


@dataclass(frozen=True)
class Node:
    id: str
    x: float
    y: float
    signalized: bool


@dataclass(frozen=True)
class Edge:
    id: str
    from_node: str
    to_node: str
    length_m: float
    speed_limit_mps: float
    lanes: int = 1

    @property
    def free_flow_time_s(self) -> float:
        return self.length_m / self.speed_limit_mps

    def storage_capacity(self, jam_spacing_m: float = DEFAULT_JAM_SPACING_M) -> int:
        """Maximum number of vehicles the edge can hold (at least one)."""
        return max(1, int(self.lanes * self.length_m / jam_spacing_m))


@dataclass(frozen=True)
class Phase:
    id: str
    approaches: tuple[str, ...]


class RoadNetwork:
    """A directed road graph with derived approaches and two-phase signal plans."""

    def __init__(self, nodes: Iterable[Node], edges: Iterable[Edge]):
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}
        for node in nodes:
            if node.id in self.nodes:
                raise NetworkError(f"Duplicate node id: {node.id}")
            self.nodes[node.id] = node
        for edge in edges:
            if edge.id in self.edges:
                raise NetworkError(f"Duplicate edge id: {edge.id}")
            self.edges[edge.id] = edge
        self.out_edges: dict[str, list[str]] = {n: [] for n in self.nodes}
        self.in_edges: dict[str, list[str]] = {n: [] for n in self.nodes}
        self._validate_and_index()
        self._phases = {n: self._derive_phases(n) for n in self.signalized_nodes}

    def _validate_and_index(self) -> None:
        for edge in self.edges.values():
            for endpoint in (edge.from_node, edge.to_node):
                if endpoint not in self.nodes:
                    raise NetworkError(f"Edge {edge.id} references unknown node {endpoint}")
            if edge.from_node == edge.to_node:
                raise NetworkError(f"Edge {edge.id} is a self-loop")
            if edge.length_m <= 0 or edge.speed_limit_mps <= 0 or edge.lanes < 1:
                raise NetworkError(f"Edge {edge.id} must have positive length, speed, and lanes")
            self.out_edges[edge.from_node].append(edge.id)
            self.in_edges[edge.to_node].append(edge.id)
        for lists in (self.out_edges, self.in_edges):
            for edge_ids in lists.values():
                edge_ids.sort()

    @property
    def signalized_nodes(self) -> list[str]:
        return sorted(n.id for n in self.nodes.values() if n.signalized)

    def approach(self, edge_id: str) -> str:
        """Compass side of the downstream node that the edge arrives from."""
        edge = self.edges[edge_id]
        src, dst = self.nodes[edge.from_node], self.nodes[edge.to_node]
        dx, dy = src.x - dst.x, src.y - dst.y
        if abs(dy) >= abs(dx):
            return "N" if dy > 0 else "S"
        return "E" if dx > 0 else "W"

    def _derive_phases(self, node_id: str) -> list[Phase]:
        present = {self.approach(e) for e in self.in_edges[node_id]}
        phases = [
            Phase(pid, tuple(a for a in approaches if a in present))
            for pid, approaches in PHASE_APPROACHES.items()
            if present.intersection(approaches)
        ]
        return phases

    def phases(self, node_id: str) -> list[Phase]:
        return self._phases.get(node_id, [])

    def phase_for_edge(self, edge_id: str) -> str | None:
        node_id = self.edges[edge_id].to_node
        approach = self.approach(edge_id)
        for phase in self.phases(node_id):
            if approach in phase.approaches:
                return phase.id
        return None

    def reverse_edge(self, edge_id: str) -> str | None:
        edge = self.edges[edge_id]
        for candidate in self.out_edges[edge.to_node]:
            if self.edges[candidate].to_node == edge.from_node:
                return candidate
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {"id": n.id, "x": n.x, "y": n.y, "signalized": n.signalized}
                for n in self.nodes.values()
            ],
            "edges": [
                {
                    "id": e.id,
                    "from": e.from_node,
                    "to": e.to_node,
                    "length_m": e.length_m,
                    "speed_limit_mps": e.speed_limit_mps,
                    "lanes": e.lanes,
                }
                for e in self.edges.values()
            ],
        }


def edge_id(a: str, b: str) -> str:
    return f"{a}->{b}"


def build_grid(
    rows: int,
    cols: int,
    block_length_m: float = 200.0,
    speed_limit_mps: float = 13.9,
    lanes: int = 1,
) -> RoadNetwork:
    """Build a rows x cols grid of signalized junctions with boundary entry/exit nodes.

    Junctions are named ``J_<row>_<col>`` (row 0 is the southern row). Boundary nodes are
    ``B_N_<col>``, ``B_S_<col>``, ``B_W_<row>``, and ``B_E_<row>``. Every road is two-way.
    """
    if rows < 1 or cols < 1:
        raise NetworkError("Grid must have at least one row and one column")
    L = block_length_m
    nodes: list[Node] = []
    for r in range(rows):
        for c in range(cols):
            nodes.append(Node(f"J_{r}_{c}", c * L, r * L, True))
    for c in range(cols):
        nodes.append(Node(f"B_S_{c}", c * L, -L, False))
        nodes.append(Node(f"B_N_{c}", c * L, rows * L, False))
    for r in range(rows):
        nodes.append(Node(f"B_W_{r}", -L, r * L, False))
        nodes.append(Node(f"B_E_{r}", cols * L, r * L, False))

    links: list[tuple[str, str]] = []
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                links.append((f"J_{r}_{c}", f"J_{r}_{c + 1}"))
            if r + 1 < rows:
                links.append((f"J_{r}_{c}", f"J_{r + 1}_{c}"))
    for c in range(cols):
        links.append((f"B_S_{c}", f"J_0_{c}"))
        links.append((f"J_{rows - 1}_{c}", f"B_N_{c}"))
    for r in range(rows):
        links.append((f"B_W_{r}", f"J_{r}_0"))
        links.append((f"J_{r}_{cols - 1}", f"B_E_{r}"))

    edges: list[Edge] = []
    for a, b in links:
        edges.append(Edge(edge_id(a, b), a, b, L, speed_limit_mps, lanes))
        edges.append(Edge(edge_id(b, a), b, a, L, speed_limit_mps, lanes))
    return RoadNetwork(nodes, edges)


def build_custom(spec: dict[str, Any]) -> RoadNetwork:
    """Build a network from explicit node and edge lists (see scenarios/corridor.yaml)."""
    try:
        nodes = [
            Node(str(n["id"]), float(n["x"]), float(n["y"]), bool(n.get("signalized", True)))
            for n in spec["nodes"]
        ]
    except (KeyError, TypeError) as exc:
        raise NetworkError(f"Invalid node definition: {exc}") from exc
    positions = {n.id: n for n in nodes}
    default_speed = float(spec.get("speed_limit_mps", 13.9))
    default_lanes = int(spec.get("lanes", 1))
    edges: list[Edge] = []
    for e in spec.get("edges", []):
        try:
            a, b = str(e["from"]), str(e["to"])
        except (KeyError, TypeError) as exc:
            raise NetworkError(f"Invalid edge definition: {e}") from exc
        if a not in positions or b not in positions:
            raise NetworkError(f"Edge {a}->{b} references an unknown node")
        length = e.get("length_m")
        if length is None:
            pa, pb = positions[a], positions[b]
            length = ((pa.x - pb.x) ** 2 + (pa.y - pb.y) ** 2) ** 0.5
        speed = float(e.get("speed_limit_mps", default_speed))
        lanes = int(e.get("lanes", default_lanes))
        edges.append(Edge(edge_id(a, b), a, b, float(length), speed, lanes))
        if e.get("bidirectional", True):
            edges.append(Edge(edge_id(b, a), b, a, float(length), speed, lanes))
    return RoadNetwork(nodes, edges)


def build_network(spec: dict[str, Any]) -> RoadNetwork:
    kind = spec.get("type", "grid")
    if kind == "grid":
        allowed = {"type", "rows", "cols", "block_length_m", "speed_limit_mps", "lanes"}
        unknown = set(spec) - allowed
        if unknown:
            raise NetworkError(f"Unknown grid network key(s): {sorted(unknown)}")
        return build_grid(
            int(spec.get("rows", 3)),
            int(spec.get("cols", 3)),
            float(spec.get("block_length_m", 200.0)),
            float(spec.get("speed_limit_mps", 13.9)),
            int(spec.get("lanes", 1)),
        )
    if kind == "custom":
        return build_custom(spec)
    raise NetworkError(f"Unknown network type: {kind!r} (expected 'grid' or 'custom')")
