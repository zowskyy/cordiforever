from __future__ import annotations

import re
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class StageResult:
    stage: str
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None


class FiveStageContract:
    """Classify → Normalize → Compute → Validate → Explain"""

    def classify(self, task: Dict[str, Any]) -> StageResult:
        task_type = "open"
        if any(k in task.get("description", "").lower() for k in ["rename", "extract", "move"]):
            task_type = "symbolic"
        elif any(k in task.get("description", "").lower() for k in ["count", "validate", "format"]):
            task_type = "exact"
        elif any(k in task.get("description", "").lower() for k in ["fix", "bug", "error"]):
            task_type = "debug"
        return StageResult("classify", True, {"type": task_type})

    def normalize(self, workspace: Path) -> StageResult:
        data = {"files": []}
        try:
            for path in workspace.rglob("*"):
                if path.is_file() and path.suffix in {".py", ".json", ".md", ".txt"}:
                    rel = path.relative_to(workspace)
                    content = path.read_text(encoding="utf-8", errors="replace")
                    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
                    path.write_text(normalized, encoding="utf-8")
                    data["files"].append(str(rel))
        except Exception as exc:
            return StageResult("normalize", False, {}, str(exc))
        return StageResult("normalize", True, data)

    def compute(self, task: Dict[str, Any], workspace: Path) -> StageResult:
        task_type = task.get("classification", {}).get("type", "open")
        if task_type == "exact":
            return self._compute_exact(task, workspace)
        if task_type == "symbolic":
            return self._compute_symbolic(task, workspace)
        return StageResult("compute", True, {"mode": "model"})

    def _compute_exact(self, task: Dict[str, Any], workspace: Path) -> StageResult:
        return StageResult("compute", True, {"mode": "exact", "counts": {}, "validations": []})

    def _compute_symbolic(self, task: Dict[str, Any], workspace: Path) -> StageResult:
        symbols = []
        for path in workspace.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        symbols.append({"file": str(path.relative_to(workspace)), "name": node.name, "line": node.lineno})
            except Exception:
                continue
        return StageResult("compute", True, {"mode": "symbolic", "symbols": symbols})

    def validate(self, workspace: Path) -> StageResult:
        issues: List[str] = []
        for path in workspace.rglob("*.py"):
            try:
                ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError as exc:
                issues.append(f"{path}: {exc}")
        return StageResult("validate", len(issues) == 0, {"issues": issues})

    def explain(self, workspace: Path) -> StageResult:
        files = []
        for path in workspace.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".json", ".md", ".txt"}:
                rel = path.relative_to(workspace)
                files.append(str(rel))
        return StageResult("explain", True, {"files_changed": files})

    def run(self, task: Dict[str, Any], workspace: Path) -> Dict[str, Any]:
        classification = self.classify(task)
        normalize = self.normalize(workspace)
        compute = self.compute({**task, "classification": classification.data}, workspace)
        validate = self.validate(workspace)
        explain = self.explain(workspace)
        return {
            "classification": classification.data,
            "normalized_files": normalize.data.get("files", []),
            "compute": compute.data,
            "validation": validate.data,
            "explanation": explain.data,
            "success": validate.success,
        }
