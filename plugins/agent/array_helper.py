from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Optional

from core.plugin import Plugin


def _safe_json_parse(text: str) -> Any:
    """Attempt to parse text as JSON, returning None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


class ArrayHelper(Plugin):
    """
    Optional capability plugin for array/list/collection reasoning.

    Detects array-related tasks deterministically (regex/keyword based),
    infers data shapes from code/data excerpts, reviews proposed tool
    actions for array-related risks, and produces bounded guidance for
    the model.

    Does NOT call the model, execute tools, or maintain independent task
    state. All results flow through the shared Context and EventBus.
    """

    name = "array_helper"
    dependencies: tuple[str, ...] = ()

    __contract__: Dict[str, Any] = {
        "requires": (),
        "provides": ("analyze_task", "analyze_context", "review_action", "build_guidance"),
        "deterministic": True,
        "zero_token": True,
    }

    # Relevance keywords (lowercase matching)
    _ARRAY_KEYWORDS = {
        "array", "arrays", "list", "lists", "item", "items",
        "product", "products", "task", "tasks", "row", "rows",
        "record", "records", "entry", "entries", "element", "elements",
        "collection", "collections", "filter", "filters", "filtered", "filtering",
        "sort", "sorts", "sorted", "sorting", "order", "ordered", "ordering",
        "search", "searches", "searching", "find", "finds", "finding", "found",
        "map", "maps", "mapping", "reduce", "reduces", "reducing",
        "aggregate", "aggregates", "aggregating", "aggregation",
        "sum", "total", "count", "average", "mean",
        "group", "groups", "grouping", "grouped",
        "page", "pages", "pagination", "paginate", "paginated",
        "index", "indexes", "indexing", "indexed",
        "slice", "slices", "slicing",
        "select", "selects", "selection", "selected",
        "delete", "deletes", "deleting", "deleted",
        "remove", "removes", "removing", "removed",
        "update", "updates", "updating", "updated",
        "add", "adds", "adding", "added",
        "append", "appends", "appending", "appended",
        "push", "pushes", "pushing", "pushed",
        "pop", "pops", "popping", "popped",
        "concat", "concatenate", "concatenates", "concatenating",
        "join", "joins", "joining", "joined",
        "split", "splits", "splitting",
        "reverse", "reverses", "reversing", "reversed",
        "deduplicate", "deduplicates", "deduplicating",
        "unique", "distinct",
        "flatten", "flattens", "flattening", "flattened",
        "nested", "nesting",
        "matrix", "matrices",
        "vector", "vectors",
        "queue", "queues",
        "stack", "stacks",
        "table", "tables",
        "grid", "grids",
    }

    # Operation patterns (compiled lazily)
    _OPERATION_PATTERNS: Dict[str, str] = {
        "filter": r"\b(filter|filtered|filtering|filters|where|selects|selecting|matching)\b",
        "sort": r"\b(sort|sorts|sorted|sorting|order|ordered|ordering|ascending|descending)\b",
        "map": r"\b(map|maps|mapping|transform|transforms|transforming)\b",
        "find": r"\b(find|finds|finding|found|search|searches|searching|lookup|look up)\b",
        "aggregate": r"\b(aggregate|aggregates|aggregating|aggregation|total|count|average|mean)\b",
        "group": r"\b(group|groups|grouping|grouped|categorize|categorizes|categorizing)\b",
        "paginate": r"\b(paginate|paginates|paginating|pagination|pages|offset)\b",
        "update": r"\b(update|updates|updating|updated|modify|modifies|modifying|modified|edit|edits|editing|edited)\b",
        "delete": r"\b(delete|deletes|deleting|deleted|remove|removes|removing|removed|drop|drops|dropping|dropped)\b",
        "add": r"\b(add|adds|adding|added|append|appends|appending|appended|push|pushes|pushing|pushed|insert|inserts|insertion|inserted)\b",
        "slice": r"\b(slice|slices|slicing|first|last|head|tail|take|skip)\b",
        "deduplicate": r"\b(deduplicate|deduplicates|deduplicating|unique|distinct|duplicates)\b",
        "flatten": r"\b(flatten|flattens|flattening|flattened|nest|nests|nesting|nested)\b",
    }

    # Maximum excerpt size for context analysis (prevents token bloat)
    _MAX_EXCERPT_LENGTH = 2000

    def __init__(self) -> None:
        super().__init__()
        self._array_facts: Dict[str, Any] = {}
        self._facts_digest: Optional[str] = None

    def start(self) -> None:
        """Initialize plugin state."""
        self._array_facts = {}
        self._facts_digest = None

    def stop(self) -> None:
        """Clean up plugin state."""
        self._array_facts = {}
        self._facts_digest = None

    def reset_run_state(self) -> None:
        """Reset per-run transient state at the beginning of each run()."""
        self._array_facts = {}
        self._facts_digest = None

    def health_check(self) -> Dict[str, Any]:
        """Verify the plugin is functional and has required capabilities."""
        return {
            "healthy": True,
            "plugin": self.name,
            "contract_version": "1.0",
            "capabilities": {
                "analyze_task": callable(getattr(self, "analyze_task", None)),
                "analyze_context": callable(getattr(self, "analyze_context", None)),
                "review_action": callable(getattr(self, "review_action", None)),
                "build_guidance": callable(getattr(self, "build_guidance", None)),
            },
        }

    def analyze_task(self, user_text: str) -> Dict[str, Any]:
        """
        Determine if the task is array-related.

        Args:
            user_text: The user's request text.

        Returns:
            Dict with: relevant (bool), confidence, operation, risks, next_action.
        """
        text_lower = user_text.lower()

        # Count keyword matches
        keyword_matches = sum(1 for kw in self._ARRAY_KEYWORDS if kw in text_lower)

        # Detect operation patterns
        detected_operations: list[str] = []
        for op, pattern in self._OPERATION_PATTERNS.items():
            if re.search(pattern, text_lower):
                detected_operations.append(op)

        # Not relevant if no keywords and no operations detected
        if keyword_matches == 0 and not detected_operations:
            return {
                "relevant": False,
                "confidence": "low",
                "operation": None,
                "risks": [],
                "next_action": None,
            }

        # Determine confidence
        if keyword_matches >= 3 or len(detected_operations) >= 2:
            confidence = "high"
        elif keyword_matches >= 2 or len(detected_operations) >= 1:
            confidence = "medium"
        else:
            confidence = "low"

        # Determine primary operation (first detected)
        primary_operation = detected_operations[0] if detected_operations else None

        # Identify risks based on operation
        risks: list[str] = []
        if primary_operation == "delete":
            risks.append("may_delete_data")
        elif primary_operation == "sort":
            risks.append("index_reordering")
        elif primary_operation == "update":
            risks.append("must_use_stable_id")
        elif primary_operation == "filter":
            risks.append("should_derive_new_view")

        # Determine next action
        next_action = None
        if confidence in ("medium", "high"):
            next_action = "Proceed with array-aware implementation."
        else:
            next_action = "Verify data structure before implementing."

        return {
            "relevant": True,
            "confidence": confidence,
            "operation": primary_operation,
            "risks": risks,
            "next_action": next_action,
        }

    def analyze_context(self, source_excerpt: str) -> Dict[str, Any]:
        """
        Infer array data shape from source code or data excerpt.

        Caps the excerpt size to prevent token bloat.

        Args:
            source_excerpt: A small excerpt of source code, JSON, or data.

        Returns:
            Dict with: representation, shape, element_type, fields,
                       mutation_risk, confidence.
        """
        excerpt = source_excerpt[:self._MAX_EXCERPT_LENGTH].strip()

        # Detect representation
        representation = "unknown"
        parsed = _safe_json_parse(excerpt)
        if isinstance(parsed, list):
            representation = "json_or_js_array"
        elif excerpt.startswith("[") and "]" in excerpt:
            if '"' in excerpt or "'" in excerpt or "{" in excerpt:
                representation = "json_or_js_array"
            else:
                representation = "python_or_js_list"
        elif excerpt.startswith("const") or excerpt.startswith("let") or excerpt.startswith("var"):
            if "=[" in excerpt or "= [" in excerpt:
                representation = "javascript_array"
        elif excerpt.startswith("import") or ("from" in excerpt and "List" in excerpt):
            representation = "typed_language_list"
        elif "np.array" in excerpt or "numpy" in excerpt.lower():
            representation = "numpy_array"
        elif "List[" in excerpt or "list[" in excerpt:
            representation = "python_typed_list"

        # Detect shape
        shape = "unknown"
        if representation in ("json_or_js_array", "python_or_js_list", "javascript_array"):
            if isinstance(parsed, list):
                # Use parsed JSON for shape detection
                if len(parsed) > 0 and isinstance(parsed[0], dict):
                    shape = "list_of_objects"
                elif len(parsed) > 0 and isinstance(parsed[0], list):
                    shape = "nested"
                else:
                    shape = "flat"
            elif "[{" in excerpt or "{[" in excerpt:
                shape = "list_of_objects"
            elif excerpt.count("[") > 2:
                shape = "nested"
            elif "{" in excerpt and "}" in excerpt:
                shape = "list_of_objects"
            else:
                shape = "flat"

        # Detect element type
        element_type = "unknown"
        if isinstance(parsed, list) and len(parsed) > 0:
            # Numerical detection from parsed JSON
            if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in parsed):
                element_type = "numbers"
            elif all(isinstance(x, dict) for x in parsed):
                element_type = "numbers_or_mixed"
                # Check if any field across all objects is numerical
                all_values = [v for obj in parsed for v in obj.values()]
                if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in all_values if v is not None):
                    element_type = "numbers_or_mixed"
            elif all(isinstance(x, str) for x in parsed):
                element_type = "strings"
            elif all(isinstance(x, bool) for x in parsed):
                element_type = "booleans"
        else:
            # Fallback regex-based detection
            if shape == "list_of_objects":
                element_type = "numbers_or_mixed"
            elif '"' in excerpt or "'" in excerpt:
                element_type = "strings"
            elif re.search(r"\b\d+\.?\d*\b", excerpt):
                element_type = "numbers"
            elif "true" in excerpt.lower() or "false" in excerpt.lower():
                element_type = "booleans"

        # Detect likely fields (for objects)
        fields: list[str] = []
        if shape == "list_of_objects":
            field_patterns = re.findall(r'"([a-zA-Z_][a-zA-Z0-9_]*)"', excerpt)
            fields = list(dict.fromkeys(field_patterns))[:8]  # dedupe, limit to 8

        # Detect mutation risk
        mutation_risk = "unknown"
        if ".sort(" in excerpt or ".reverse(" in excerpt:
            mutation_risk = "high"
        elif ".filter(" in excerpt or ".map(" in excerpt:
            mutation_risk = "low"
        elif "toSorted" in excerpt or "toReversed" in excerpt:
            mutation_risk = "low"

        # Determine confidence
        confidence = "low"
        if representation != "unknown" and shape != "unknown":
            # Empty list — nothing to infer
            if isinstance(parsed, list) and len(parsed) == 0:
                confidence = "low"
            else:
                confidence = "medium"
        if representation != "unknown" and shape != "unknown" and element_type != "unknown":
            if not (isinstance(parsed, list) and len(parsed) == 0):
                confidence = "high"

        return {
            "representation": representation,
            "shape": shape,
            "element_type": element_type,
            "fields": fields,
            "mutation_risk": mutation_risk,
            "confidence": confidence,
        }

    def review_action(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        array_facts: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Review a proposed tool action for array-related risks.

        Args:
            tool_name: The tool being called (e.g., "write_file").
            arguments: The tool arguments.
            array_facts: Current array facts from analyze_task/analyze_context.

        Returns:
            Dict with: status ("pass"|"warn"), reason, required_checks.
        """
        status = "pass"
        reason = ""
        required_checks: list[str] = []

        if tool_name == "write_file":
            content = arguments.get("content", "")
            if not isinstance(content, str):
                return {"status": "pass", "reason": "", "required_checks": []}

            # Check for in-place mutation patterns
            if ".sort(" in content and "toSorted" not in content:
                status = "warn"
                reason = "Using .sort() may mutate the source array. Consider copying first."
                required_checks = ["Verify source array order is preserved if required."]

            elif ".reverse(" in content and "toReversed" not in content:
                status = "warn"
                reason = "Using .reverse() may mutate the source array. Consider copying first."
                required_checks = ["Verify source array order is preserved if required."]

            elif ".splice(" in content:
                status = "warn"
                reason = "Using .splice() mutates the source array. Ensure this is intentional."
                required_checks = ["Verify source array mutation is intended.", "Check empty array handling."]

            elif array_facts.get("shape") == "list_of_objects":
                if "update" in content.lower() or "edit" in content.lower():
                    if "id" not in content.lower() and "_id" not in content.lower():
                        status = "warn"
                        reason = "Updating objects without a stable ID is fragile."
                        required_checks = ["Verify update uses a stable identifier."]

            # Check for unsafe index access
            if array_facts.get("shape") in ("flat", "list_of_objects"):
                if "[0]" in content:
                    status = "warn"
                    reason = "Accessing array by index [0] without empty check."
                    required_checks = ["Test with empty array.", "Test with single item."]

            # Numerical-specific checks
            if array_facts.get("element_type") in ("numbers", "numbers_or_mixed"):
                # Integer division risk: / operator used where Math.floor/round is needed
                if re.search(r"[^.]/[^/=]", content) and "Math.floor" not in content and "Math.round" not in content:
                    if "reduce" not in content and ".reduce" not in content:
                        status = "warn"
                        reason = "Division on numerical arrays may cause floating-point or integer division issues."
                        required_checks = ["Use Math.floor/Math.round for integer division.", "Test with float inputs."]

                # Division by zero risk: array index in denominator
                if re.search(r"nums\[\d+\]|arr\[\d+\]|items\[\d+\]", content):
                    if "/" in content:
                        status = "warn"
                        reason = "Division by array element risks division by zero."
                        required_checks = ["Guard against zero divisor.", "Test with zero values."]

            # Check for reassignment of source collection (not just assignment from it)
            if array_facts.get("operation") == "filter":
                # Only warn if the source collection itself is reassigned to a new value
                # (e.g., "items = [...]") not when it's read as input (e.g., "x = items.filter(...)")
                import re as _re
                if _re.search(r'\b(items|tasks|records|products|entries)\s*=\s*\[', content):
                    if status != "warn":
                        status = "warn"
                        reason = "Reassigning source collection may lose data. Derive a new view."
                        required_checks = ["Verify original collection is preserved."]

        return {
            "status": status,
            "reason": reason,
            "required_checks": required_checks,
        }

    def build_guidance(self, array_facts: Dict[str, Any]) -> str:
        """
        Build compact, bounded guidance for the model.

        Target: 40-100 tokens. Never injects more than ~200 characters.

        Args:
            array_facts: Current array facts from analysis.

        Returns:
            A short natural-language fact sheet.
        """
        guidance_parts: list[str] = []

        # Representation and shape
        representation = array_facts.get("representation", "unknown")
        shape = array_facts.get("shape", "unknown")

        if representation != "unknown" and shape != "unknown":
            guidance_parts.append(
                f"Array facts: Data is a {shape} {representation.replace('_', ' ')}."
            )

        # Operation
        operation = array_facts.get("operation")
        if operation:
            if operation == "filter":
                guidance_parts.append("Derive a new filtered view; do not replace the source collection.")
            elif operation == "sort":
                guidance_parts.append("Sort a copy or use non-mutating methods to preserve source order.")
            elif operation == "update":
                guidance_parts.append("Update items by stable ID, not by position or display text.")
            elif operation == "delete":
                guidance_parts.append("Remove items by ID; handle missing ID gracefully.")
            elif operation == "paginate":
                guidance_parts.append("Handle empty collections and out-of-range pages.")

        # Mutation risk
        mutation_risk = array_facts.get("mutation_risk")
        if mutation_risk == "high":
            guidance_parts.append("High mutation risk: ensure source data preservation is intentional.")

        # Required checks
        required_checks = array_facts.get("required_checks", [])
        if required_checks:
            guidance_parts.append("Required checks: " + "; ".join(required_checks[:3]) + ".")

        # Numerical array guidance
        if array_facts.get("element_type") in ("numbers", "numbers_or_mixed"):
            if array_facts.get("operation") in ("aggregate", "filter", "map"):
                guidance_parts.append("Numbers: guard against empty arrays, division by zero, and floating-point precision limits.")

        # Default empty handling
        guidance_parts.append("Handle empty, single-item, and normal lists.")

        return " ".join(guidance_parts)

    def _compute_facts_digest(self, facts: Dict[str, Any]) -> str:
        """Compute a stable hash of array facts for change detection."""
        facts_json = json.dumps(facts, sort_keys=True, default=str)
        return hashlib.sha256(facts_json.encode("utf-8")).hexdigest()

    def update_facts(self, facts: Dict[str, Any]) -> bool:
        """
        Update internal array facts and detect changes.

        Args:
            facts: New array facts from analysis.

        Returns:
            True if facts changed, False if unchanged.
        """
        new_digest = self._compute_facts_digest(facts)
        changed = new_digest != self._facts_digest
        if changed:
            self._array_facts = facts
            self._facts_digest = new_digest
        return changed

    def get_facts(self) -> Dict[str, Any]:
        """Get current array facts (returns a copy)."""
        return self._array_facts.copy()

    def clear_facts(self) -> None:
        """Clear array facts."""
        self._array_facts = {}
        self._facts_digest = None
