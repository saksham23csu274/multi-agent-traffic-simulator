"""Shortest-path routing over the road graph."""

from __future__ import annotations

import heapq
from typing import Callable, Collection

from .network import RoadNetwork

EdgeCost = Callable[[str], float]


def free_flow_cost(network: RoadNetwork) -> EdgeCost:
    return lambda edge_id: network.edges[edge_id].free_flow_time_s


def shortest_path(
    network: RoadNetwork,
    origin: str,
    destination: str,
    cost: EdgeCost,
    blocked: Collection[str] = (),
) -> tuple[list[str], float] | None:
    """Dijkstra's algorithm from ``origin`` to ``destination`` node.

    Returns ``(edge_ids, total_cost)`` or ``None`` when no path avoids ``blocked`` edges.
    Ties are broken deterministically by insertion order and node id.
    """
    if origin == destination:
        return [], 0.0
    best: dict[str, float] = {origin: 0.0}
    via: dict[str, str] = {}
    counter = 0
    frontier: list[tuple[float, int, str]] = [(0.0, counter, origin)]
    done: set[str] = set()
    while frontier:
        dist, _, node = heapq.heappop(frontier)
        if node in done:
            continue
        if node == destination:
            break
        done.add(node)
        for eid in network.out_edges[node]:
            if eid in blocked:
                continue
            nxt = network.edges[eid].to_node
            if nxt in done:
                continue
            candidate = dist + cost(eid)
            if candidate < best.get(nxt, float("inf")):
                best[nxt] = candidate
                via[nxt] = eid
                counter += 1
                heapq.heappush(frontier, (candidate, counter, nxt))
    if destination not in via:
        return None
    path: list[str] = []
    node = destination
    while node != origin:
        eid = via[node]
        path.append(eid)
        node = network.edges[eid].from_node
    path.reverse()
    return path, best[destination]


def route_cost(route: list[str], cost: EdgeCost) -> float:
    return sum(cost(e) for e in route)
