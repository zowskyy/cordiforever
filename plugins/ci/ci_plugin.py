"""
CI Plugin — brings GitHub CI status into the pool.

Queries the gh CLI for recent workflow runs and emits events.
Zero tokens — uses subprocess to call gh.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class CIRun:
    run_id: str
    status: str = "unknown"
    conclusion: str = "unknown"
    created_at: str = ""
    url: str = ""
    timestamp: float = field(default_factory=time.time)


class CIPlugin(EventDrivenPlugin):
    name = "ci_plugin"
    dependencies = ()

    def __init__(self, repo: str | None = None, workflow: str = "Long-Horizon Benchmark.yml") -> None:
        super().__init__()
        self._repo = repo
        self._workflow = workflow
        self._runs: list[CIRun] = []
        self._max_runs = 20
        self._cache_ttl = 30
        self._last_fetch = 0.0

    def start(self) -> None:
        # Auto-detect repo from git remote if not explicitly provided
        if self._repo is None:
            detected = self._detect_repo()
            if detected:
                self._repo = detected

    def stop(self) -> None:
        pass

    def _detect_repo(self) -> str | None:
        try:
            result = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                url = result.stdout.strip()
                # Parse github.com:user/repo(.git)
                m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
                if m:
                    repo = m.group(1).strip("/")
                    # ensure owner/repo format
                    if "/" in repo and len(repo.split("/")) == 2:
                        return repo
                # fallback: last two path parts
                parts = url.rstrip("/").replace(":", "/").split("/")
                if len(parts) >= 2:
                    candidate = f"{parts[-2]}/{parts[-1].replace('.git','')}"
                    if "/" in candidate:
                        return candidate
        except Exception:
            pass
        return None

    def get_status(self) -> dict[str, Any]:
        if time.time() - self._last_fetch > self._cache_ttl:
            self._refresh()
        if not self._runs:
            return {"status": "unknown", "message": "No CI runs found"}
        latest = self._runs[0]
        return {
            "status": latest.conclusion,
            "run_id": latest.run_id,
            "created_at": latest.created_at,
            "url": latest.url,
            "message": f"CI {latest.conclusion.upper()} ({latest.run_id})",
        }

    def run_benchmark(self) -> str:
        return "Benchmark execution is handled by GitHub Actions. Use /ci to check status."

    def _refresh(self) -> None:
        try:
            cmd = [
                "gh", "run", "list",
                "--repo", self._repo,
                "--workflow", self._workflow,
                "--limit", "5",
                "--json", "status,conclusion,createdAt,url,databaseId",
                "--jq", ".[0]",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                run = CIRun(
                    run_id=str(data.get("databaseId", "")),
                    status=data.get("status", "unknown"),
                    conclusion=data.get("conclusion", "unknown"),
                    created_at=data.get("createdAt", ""),
                    url=data.get("url", ""),
                )
                self._runs.insert(0, run)
                if len(self._runs) > self._max_runs:
                    self._runs.pop()
                self._last_fetch = time.time()
                self._emit_event(run)
        except Exception:
            pass

    def _emit_event(self, run: CIRun) -> None:
        if self.context is not None:
            self.context.events.emit("ci.status.updated", {
                "run_id": run.run_id,
                "status": run.status,
                "conclusion": run.conclusion,
                "created_at": run.created_at,
                "url": run.url,
            })
