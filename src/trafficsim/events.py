"""Structured event log and in-process message bus."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import Message


class EventLog:
    """Append-only, simulation-time-stamped event log."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, time_s: float, type: str, source: str, **data: Any) -> None:
        self.events.append({"time_s": round(time_s, 3), "type": type, "source": source, **data})

    def of_type(self, *types: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] in types]

    def count(self, type: str) -> int:
        return sum(1 for e in self.events if e["type"] == type)


class MessageBus:
    """Topic-based publish/subscribe with per-agent inboxes, drained in publish order."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[str]] = defaultdict(set)
        self._inboxes: dict[str, list[Message]] = defaultdict(list)

    def subscribe(self, agent_id: str, topic: str) -> None:
        self._subscribers[topic].add(agent_id)

    def publish(self, message: Message) -> None:
        for agent_id in sorted(self._subscribers.get(message.topic, ())):
            self._inboxes[agent_id].append(message)

    def receive(self, agent_id: str) -> list[Message]:
        return self._inboxes.pop(agent_id, [])
