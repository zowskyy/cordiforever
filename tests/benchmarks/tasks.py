"""Benchmark task definitions for ArrayHelper evaluation.

Each task defines a representative array operation with expected outputs
that can be verified deterministically (no model calls needed for verification).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ArrayTask:
    """A benchmark task for array-related operations."""
    name: str
    description: str
    user_input: str
    # Source file content that must exist before the task
    source_file: str = "data.js"
    source_content: str = ""
    # Verification function: takes workspace Path, returns bool
    verify: Callable[[Any], bool] = lambda ws: False
    # Expected number of model rounds (approximate, for metrics)
    expected_rounds_min: int = 1
    expected_rounds_max: int = 5
    metadata: dict[str, Any] = field(default_factory=dict)
    # Tags for categorization
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Filter tasks
# ---------------------------------------------------------------------------

FILTER_TASKS = [
    ArrayTask(
        name="filter_active_items",
        description="Filter a list to show only active items",
        user_input="Filter the list to show only active items",
        source_file="products.js",
        source_content=(
            'const products = [\n'
            '  { id: 1, name: "Widget", active: true },\n'
            '  { id: 2, name: "Gadget", active: false },\n'
            '  { id: 3, name: "Doohickey", active: true },\n'
            '];\n'
            'const active = products.filter(p => p.active);\n'
        ),
        verify=lambda ws: (ws / "products.js").read_text(encoding="utf-8").count("active: true") >= 2,
        tags=["filter", "basic"],
    ),
    ArrayTask(
        name="filter_by_status",
        description="Filter tasks by completed status",
        user_input="Filter tasks to show only completed ones",
        source_file="tasks.js",
        source_content=(
            'const tasks = [\n'
            '  { id: 1, text: "Buy milk", completed: true },\n'
            '  { id: 2, text: "Walk dog", completed: false },\n'
            '  { id: 3, text: "Pay bills", completed: true },\n'
            '];\n'
        ),
        verify=lambda ws: (ws / "tasks.js").read_text(encoding="utf-8").count("completed: true") >= 2,
        tags=["filter", "basic"],
    ),
    ArrayTask(
        name="filter_empty_query_shows_all",
        description="Filter with empty query should show all items",
        user_input="Filter the list, handle empty search by showing all items",
        source_file="items.js",
        source_content=(
            'const items = [{ id: 1, name: "a" }, { id: 2, name: "b" }];\n'
            'const query = "";\n'
            'const results = items.filter(item => query === "" || item.name.includes(query));\n'
        ),
        verify=lambda ws: "includes(query)" in (ws / "items.js").read_text(encoding="utf-8"),
        tags=["filter", "empty-handle"],
    ),
]

# ---------------------------------------------------------------------------
# Sort tasks
# ---------------------------------------------------------------------------

SORT_TASKS = [
    ArrayTask(
        name="sort_by_price_asc",
        description="Sort products by price ascending",
        user_input="Sort products by price in ascending order",
        source_file="products.js",
        source_content=(
            'const products = [\n'
            '  { id: 3, name: "Cheap", price: 10 },\n'
            '  { id: 1, name: "Expensive", price: 100 },\n'
            '  { id: 2, name: "Medium", price: 50 },\n'
            '];\n'
        ),
        verify=lambda ws: "sort" in (ws / "products.js").read_text(encoding="utf-8"),
        tags=["sort", "basic"],
    ),
    ArrayTask(
        name="sort_stable",
        description="Sort should be stable (preserve relative order of equal elements)",
        user_input="Sort products by price, keeping same-price items in original order",
        source_file="products.js",
        source_content=(
            'const products = [\n'
            '  { id: 1, name: "A", price: 10 },\n'
            '  { id: 2, name: "B", price: 10 },\n'
            '  { id: 3, name: "C", price: 5 },\n'
            '];\n'
        ),
        verify=lambda ws: "sort" in (ws / "products.js").read_text(encoding="utf-8"),
        tags=["sort", "stability"],
    ),
]

# ---------------------------------------------------------------------------
# Update tasks
# ---------------------------------------------------------------------------

UPDATE_TASKS = [
    ArrayTask(
        name="update_by_id",
        description="Update a record by its ID",
        user_input="Update the product with ID 2 to have price 75",
        source_file="products.js",
        source_content=(
            'const products = [\n'
            '  { id: 1, name: "Widget", price: 10 },\n'
            '  { id: 2, name: "Gadget", price: 50 },\n'
            '];\n'
        ),
        verify=lambda ws: "75" in (ws / "products.js").read_text(encoding="utf-8"),
        tags=["update", "by-id"],
    ),
]

# ---------------------------------------------------------------------------
# Delete tasks
# ---------------------------------------------------------------------------

DELETE_TASKS = [
    ArrayTask(
        name="delete_by_id",
        description="Delete a record by its ID",
        user_input="Delete the product with ID 1",
        source_file="products.js",
        source_content=(
            'const products = [\n'
            '  { id: 1, name: "Widget" },\n'
            '  { id: 2, name: "Gadget" },\n'
            '];\n'
        ),
        verify=lambda ws: 'filter(' in (ws / "products.js").read_text(encoding="utf-8"),
        tags=["delete", "by-id"],
    ),
]

# ---------------------------------------------------------------------------
# Aggregate tasks
# ---------------------------------------------------------------------------

AGGREGATE_TASKS = [
    ArrayTask(
        name="count_completed",
        description="Count completed tasks",
        user_input="Count how many tasks are completed",
        source_file="tasks.js",
        source_content=(
            'const tasks = [\n'
            '  { id: 1, completed: true },\n'
            '  { id: 2, completed: false },\n'
            '  { id: 3, completed: true },\n'
            '];\n'
        ),
        verify=lambda ws: "length" in (ws / "tasks.js").read_text(encoding="utf-8"),
        tags=["aggregate", "count"],
    ),
    ArrayTask(
        name="sum_values",
        description="Sum all numeric values in an array",
        user_input="Calculate the sum of all prices",
        source_file="products.js",
        source_content=(
            'const products = [\n'
            '  { id: 1, price: 10 },\n'
            '  { id: 2, price: 30 },\n'
            '  { id: 3, price: 50 },\n'
            '];\n'
        ),
        verify=lambda ws: "reduce" in (ws / "products.js").read_text(encoding="utf-8"),
        tags=["aggregate", "sum"],
    ),
]

# ---------------------------------------------------------------------------
# Find/search tasks
# ---------------------------------------------------------------------------

FIND_TASKS = [
    ArrayTask(
        name="find_by_name",
        description="Find an item by its name",
        user_input="Find the product named 'Widget'",
        source_file="products.js",
        source_content=(
            'const products = [\n'
            '  { id: 1, name: "Widget", price: 10 },\n'
            '  { id: 2, name: "Gadget", price: 20 },\n'
            '];\n'
        ),
        verify=lambda ws: "find(" in (ws / "products.js").read_text(encoding="utf-8"),
        tags=["find", "search"],
    ),
]

# ---------------------------------------------------------------------------
# All tasks
# ---------------------------------------------------------------------------

ALL_ARRAY_TASKS: list[ArrayTask] = (
    FILTER_TASKS + SORT_TASKS + UPDATE_TASKS + DELETE_TASKS + AGGREGATE_TASKS + FIND_TASKS
)


def get_tasks_by_tag(tag: str) -> list[ArrayTask]:
    """Filter tasks by tag."""
    return [t for t in ALL_ARRAY_TASKS if tag in t.tags]
