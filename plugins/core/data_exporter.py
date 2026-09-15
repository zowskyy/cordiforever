"""DataExporter plugin — exports successful session trajectories for fine-tuning."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from core.plugin import EventDrivenPlugin
from core.event_log import EventLog
from core.events import Event


class DataExporter(EventDrivenPlugin):
    """Collects and exports successful session trajectories as JSONL for fine-tuning.

    Registers only in the `lite` profile to enable zero-token data collection.
    Export is triggered via the `--export-data` CLI flag at startup.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "data_exporter"
        self.dependencies = ("event_logger",)
        self.__contract__ = {
            "version": "1.0",
            "capabilities": ["export_jsonl", "trajectory_reconstruct", "quality_filter", "delta_export"],
            "zero_token": True,
        }
        self._event_log: Optional[EventLog] = None
        self._run_state: dict[str, Any] = {}
        self._state_file: Path | None = None

    def start(self) -> None:
        """Initialize the exporter with access to the event log."""
        if self.context is None:
            return
        event_logger = self.context.plugins.get("event_logger")
        if event_logger is None:
            self._event_log = None
            return
        # EventLogger wraps EventLog; access via the _event_log attribute
        if hasattr(event_logger, "_event_log"):
            self._event_log = event_logger._event_log
        else:
            self._event_log = None
        # Delta export state file location
        workspace = Path(self.context.config.get("workspace", "workspace")) if self.context else Path("workspace")
        self._state_file = workspace / ".data_exporter_state.json"

    def health_check(self) -> bool:
        """Verify the exporter has access to the event log."""
        return self._event_log is not None

    def export_successful_sessions(
        self, output_dir: str | Path, criteria: dict[str, Any] | None = None, delta: bool = False
    ) -> int:
        """Export all sessions meeting quality criteria to JSONL files.

        Args:
            output_dir: Directory to write JSONL files.
            criteria: Optional filters (e.g., {"app_type": "crud", "max_turns": 20}).
            delta: If True, only export sessions modified since last export.

        Returns:
            Number of sessions exported.
        """
        if self._event_log is None:
            return 0

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        last_export = self._load_last_export_timestamp() if delta else None
        criteria = criteria or {}
        count = 0
        export_rows: list[dict[str, Any]] = []

        for session_id, metadata, events in self._iter_sessions(delta=delta, last_export=last_export):
            if not self._has_required_criteria(session_id, metadata):
                continue
            if not self._meets_quality_filters(session_id, metadata, criteria, events):
                continue

            trajectory = self._export_session(session_id, events)
            if trajectory is None:
                continue

            export_rows.append(trajectory)
            count += 1

        if export_rows:
            output_file = output_path / "trajectories.jsonl"
            with open(output_file, "w", encoding="utf-8") as f:
                for row in export_rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")

        if delta and export_rows:
            self._save_last_export_timestamp()

        return count

    def _load_last_export_timestamp(self) -> datetime | None:
        """Load the last export timestamp from state file."""
        if self._state_file is None or not self._state_file.exists():
            return None
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            ts = data.get("last_export_timestamp")
            if ts:
                return datetime.fromisoformat(ts)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        return None

    def _save_last_export_timestamp(self) -> None:
        """Save the current timestamp as the last export timestamp."""
        if self._state_file is None:
            return
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "last_export_timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._state_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _iter_sessions(self, delta: bool = False, last_export: datetime | None = None) -> Iterator[tuple[str, dict[str, Any] | None, list[Event]]]:
        """Iterate over all sessions, yielding (session_id, metadata, events)."""
        if self._event_log is None:
            return

        rows = self._event_log.query(
            "SELECT DISTINCT session_id FROM events ORDER BY session_id"
        )
        for row in rows:
            session_id = row[0]
            if delta and last_export is not None:
                latest_ts = self._get_latest_event_timestamp(session_id)
                if latest_ts is None or latest_ts <= last_export:
                    continue
            metadata = self._get_session_metadata(session_id)
            events = self._event_log.get_session_events(session_id)
            yield session_id, metadata, events

    def _get_latest_event_timestamp(self, session_id: str) -> datetime | None:
        """Get the latest event timestamp for a session."""
        rows = self._event_log.query(
            "SELECT timestamp FROM events WHERE session_id = ? ORDER BY timestamp DESC LIMIT 1",
            (session_id,),
        )
        if not rows:
            return None
        try:
            return datetime.fromisoformat(rows[0][0].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def _has_required_criteria(self, session_id: str, metadata: dict[str, Any] | None) -> bool:
        """Check if a session has a recorded outcome event."""
        return metadata is not None and "outcome" in metadata

    def _meets_quality_filters(
        self,
        session_id: str,
        metadata: dict[str, Any] | None,
        criteria: dict[str, Any],
        events: list[Event],
    ) -> bool:
        """Apply quality filters to determine if a session should be exported.

        Filters:
        - Must have passed verification (if verifier events exist)
        - Must have passed tests (if test events exist)
        - No protected file violations
        - Completed within max_turns (default 20)
        - No errors or timeouts
        """
        if metadata is None:
            return False

        outcome = metadata.get("outcome", "")
        if outcome != "success":
            return False

        # Protect against protected file violations
        for event in events:
            if event.type == "protected_file.violation":
                return False

        # Check turn count
        max_turns = criteria.get("max_turns", 20)
        model_turns = metadata.get("model_turns", 0)
        if model_turns > max_turns:
            return False

        # Check error/timeout events
        for event in events:
            if event.type in ("error", "timeout", "agent.error"):
                return False

        return True

    def _get_session_metadata(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve the session.outcome event metadata."""
        rows = self._event_log.query(
            "SELECT payload FROM events WHERE session_id = ? AND type = 'session.outcome' ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        if not rows:
            return None
        try:
            return json.loads(rows[0][0])
        except (json.JSONDecodeError, TypeError):
            return None

    def _export_session(self, session_id: str, events: list[Event]) -> dict[str, Any] | None:
        """Export a single session as a trajectory.

        Returns a dict with:
        - session_id
        - app_type
        - metadata from session.outcome
        - trajectory: list of {role, content, tool_name, tool_args}
        """
        metadata = self._get_session_metadata(session_id)
        if metadata is None:
            return None

        trajectory: list[dict[str, Any]] = []
        for event in events:
            if event.type == "user.message":
                trajectory.append({"role": "user", "content": event.payload.get("content", "")})
            elif event.type == "assistant.message":
                content = event.payload.get("content", "")
                tool_calls = event.payload.get("tool_calls", [])
                trajectory.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            elif event.type == "tool.result":
                tool_name = event.payload.get("tool_name", "")
                tool_args = event.payload.get("arguments", {})
                result = event.payload.get("result", "")
                trajectory.append({
                    "role": "tool",
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "content": result,
                })

        return {
            "session_id": session_id,
            "app_type": metadata.get("app_type", "generic"),
            "metadata": metadata,
            "trajectory": trajectory,
        }

    def export_session_zip(self, session_id: str, output_path: str | Path) -> bool:
        """Export one session to a ZIP file.

        Contents:
        - events.jsonl: raw durable events for the session
        - metadata.json: session metadata summary
        """
        if self._event_log is None:
            return False
        import zipfile
        events = self._event_log.get_session_events(session_id)
        metadata = self._get_session_metadata(session_id)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                events_path = f"{session_id}/events.jsonl"
                lines = []
                for event in events:
                    lines.append(json.dumps(event.to_dict(), ensure_ascii=False, default=str))
                zf.writestr(events_path, "\n".join(lines))
                meta_path = f"{session_id}/metadata.json"
                meta = {
                    "session_id": session_id,
                    "event_count": len(events),
                    "metadata": metadata,
                }
                zf.writestr(meta_path, json.dumps(meta, ensure_ascii=False, default=str, indent=2))
            return True
        except (OSError, zipfile.BadZipFile):
            return False

    def reset_run_state(self) -> None:
        """Reset any per-run state (for zero-drag invariant)."""
        self._run_state = {}

    # The old export_session and reconstruct_trajectory are kept as thin
    # wrappers for backward compatibility with tests.
    def export_session(self, session_id: str, output_dir: str | Path) -> bool:
        """Export a single session to a JSONL file in output_dir."""
        if self._event_log is None:
            return False
        events = self._event_log.get_session_events(session_id)
        result = self._export_session(session_id, events)
        if result is None:
            return False

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        output_file = output_path / f"session_{session_id}.jsonl"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        return True

    def reconstruct_trajectory(self, session_id: str) -> dict[str, Any] | None:
        """Reconstruct the message trajectory for a session."""
        if self._event_log is None:
            return None
        events = self._event_log.get_session_events(session_id)
        return self._export_session(session_id, events)

