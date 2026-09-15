from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from .events import Event
from .event_log import EventLog


class LifecycleConsolidator:
    """EverMemOS-style thematic clustering with salience/recurrence/utility triggers."""

    def __init__(self, event_log: EventLog, cluster_threshold: int = 20, salience_threshold: float = 0.5) -> None:
        self._event_log = event_log
        self._cluster_threshold = cluster_threshold
        self._salience_threshold = salience_threshold
        self._tool_weights: dict[str, float] = {
            "file_read": 0.3,
            "file_write": 0.7,
            "file_list": 0.2,
            "file_search": 0.6,
            "code_check": 0.5,
            "regex_search": 0.4,
        }

    def maybe_consolidate(self, session_id: str) -> list[dict[str, Any]]:
        events = self._event_log.get_session_events(session_id)
        if len(events) < self._cluster_threshold:
            return []

        clusters = self._cluster_events(events)
        summaries = []
        for cluster_id, cluster_events in clusters.items():
            salience = self._compute_salience(cluster_events)
            recurrence = self._compute_recurrence(cluster_id, events)
            utility = self._compute_utility(cluster_events)

            if salience >= self._salience_threshold or recurrence >= 3 or utility >= 0.7:
                summary = self._summarize_cluster(cluster_events, cluster_id, salience, recurrence, utility)
                summaries.append(summary)
        return summaries

    def _cluster_events(self, events: list[Event]) -> dict[str, list[Event]]:
        clusters: dict[str, list[Event]] = {}
        for event in events:
            topic = self._extract_topic(event)
            clusters.setdefault(topic, []).append(event)
        return clusters

    def _extract_topic(self, event: Event) -> str:
        payload = event.payload or {}
        if payload.get("tool_name"):
            return payload["tool_name"]
        text_parts = [event.type]
        if payload.get("content"):
            text_parts.append(str(payload["content"]))
        text = " ".join(text_parts).lower()
        tokens = [t for t in text.split() if len(t) > 3]
        if not tokens:
            return "general"
        most_common = Counter(tokens).most_common(1)[0][0]
        return most_common

    def _compute_salience(self, events: list[Event]) -> float:
        if not events:
            return 0.0
        total = 0.0
        for event in events:
            payload = event.payload or {}
            tool = payload.get("tool_name", "")
            weight = self._tool_weights.get(tool, 0.1)
            if payload.get("success") is False:
                weight *= 1.5
            total += weight
        return min(total / len(events), 1.0)

    def _compute_recurrence(self, topic: str, all_events: list[Event]) -> int:
        count = 0
        for event in all_events:
            if self._extract_topic(event) == topic:
                count += 1
        return count

    def _compute_utility(self, events: list[Event]) -> float:
        if not events:
            return 0.0
        successes = sum(1 for e in events if (e.payload or {}).get("success") is not False)
        return successes / len(events)

    def _summarize_cluster(self, events: list[Event], topic: str, salience: float, recurrence: int, utility: float) -> dict[str, Any]:
        tool_counts: dict[str, int] = {}
        files: set[str] = set()
        errors = 0
        for event in events:
            payload = event.payload or {}
            if payload.get("tool_name"):
                tool_counts[payload["tool_name"]] = tool_counts.get(payload["tool_name"], 0) + 1
            if payload.get("arguments", {}).get("path"):
                files.add(payload["arguments"]["path"])
            if payload.get("success") is False:
                errors += 1

        top_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        return {
            "topic": topic,
            "event_count": len(events),
            "tools_used": [t[0] for t in top_tools],
            "files_involved": sorted(files),
            "error_count": errors,
            "salience": round(salience, 2),
            "recurrence": recurrence,
            "utility": round(utility, 2),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
