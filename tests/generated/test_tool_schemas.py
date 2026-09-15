"""Generated validation for registered tool schemas.

This test ensures that every tool schema exposed by FileTools (and any other
schema provider) is well-formed JSON and contains the required top-level keys
expected by the model-facing contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_file_tools_schemas_are_valid_json() -> None:
    """FileTools.schemas() must return parseable JSON structures."""
    # Import lazily so the test can run without full app startup.
    import sys
    sys.path.insert(0, str(REPO))
    from plugins.tools.file import FileTools
    from core.context import Context

    # Minimal context stub for schema generation
    ctx = Context(config={"workspace": str(REPO / "workspace")})
    ft = FileTools(ctx.config["workspace"])
    schemas = ft.schemas()

    assert isinstance(schemas, list)
    assert len(schemas) > 0

    for schema in schemas:
        assert isinstance(schema, dict)
        assert "type" in schema
        assert schema["type"] == "function"
        assert "function" in schema
        fn = schema["function"]
        assert isinstance(fn, dict)
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        # parameters must be a dict with a 'type' key (JSON Schema object)
        assert isinstance(fn["parameters"], dict)
        assert "type" in fn["parameters"]


def test_tool_schema_names_are_unique() -> None:
    """Tool schema names must be unique to avoid model confusion."""
    import sys
    sys.path.insert(0, str(REPO))
    from plugins.tools.file import FileTools
    from core.context import Context

    ctx = Context(config={"workspace": str(REPO / "workspace")})
    ft = FileTools(ctx.config["workspace"])
    schemas = ft.schemas()

    names = [s["function"]["name"] for s in schemas]
    assert len(names) == len(set(names)), f"Duplicate tool names: {names}"


def test_tool_schema_descriptions_are_non_empty() -> None:
    """Every tool must have a non-empty description for the model."""
    import sys
    sys.path.insert(0, str(REPO))
    from plugins.tools.file import FileTools
    from core.context import Context

    ctx = Context(config={"workspace": str(REPO / "workspace")})
    ft = FileTools(ctx.config["workspace"])
    schemas = ft.schemas()

    for schema in schemas:
        fn = schema["function"]
        desc = fn.get("description", "").strip()
        assert desc, f"Tool '{fn.get('name')}' has an empty description"


def test_tool_schema_parameters_are_valid_json_schema() -> None:
    """Tool parameters must be valid JSON Schema objects."""
    import sys
    sys.path.insert(0, str(REPO))
    from plugins.tools.file import FileTools
    from core.context import Context

    ctx = Context(config={"workspace": str(REPO / "workspace")})
    ft = FileTools(ctx.config["workspace"])
    schemas = ft.schemas()

    for schema in schemas:
        fn = schema["function"]
        params = fn.get("parameters", {})
        assert isinstance(params, dict)
        assert params.get("type") in ("object", None)
        if params.get("type") == "object":
            assert "properties" in params or "required" in params
