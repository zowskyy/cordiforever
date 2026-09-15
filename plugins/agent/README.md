# agent — routing, loop, and orchestration

Agent-facing plugins that own routing, parameter extraction, multi-domain dispatch, aggregation, and the main event loop.

## Plugins

- AgentLoop — main turn loop
- MultiDomainRouter — domain selection
- ParameterExtractor — argument normalization
- QuerySplitter — decomposition
- AggregateResponse — response merging
- SemanticRouter — optional embedding-based routing (full profile only)
- SchemaRouter — compact schema mode for 1.5B (lite default)
- ArrayHelper — deterministic array task reasoning (lite + full)
- AppVerifier — deterministic app completion verification (lite + full)
- DataExporter — trajectory export for fine-tuning (lite + full)

## SchemaRouter

SchemaRouter provides compact tool schemas to reduce token overhead for
the 1.5B model. In `lite` profile, it is enabled with
`compact_schema=True` by default. It replaces verbose function schemas with
a single `call_tool(tool_name, arguments)` dispatcher that expands to real
tools only when needed.

Logical tools: `read`, `write`, `list`, `delete`, `done`.

Expansion maps:
- `read` → `read_file`
- `write` → `write_file`
- `list` → `list_directory`
- `delete` → `delete_file`

The model sees one `call_tool` schema instead of N individual tool
schemas, cutting visible tokens by >=80%.

### Configuration

```text
config["schema_router_enabled"]  # enable/disable the router
config["compact_schema"]         # True = compact, False = verbose schemas
```

- `lite` profile: `schema_router_enabled=True`, `compact_schema=True`
- `full` profile: `schema_router_enabled=True`, `compact_schema=False`
- CLI: `--no-compact-schema` (lite), `--compact-schema` (full)

## ArrayHelper

ArrayHelper is a deterministic, zero-token plugin that detects array-related
tasks and provides bounded guidance on data shapes, operations, and risks.

Capabilities:
- `analyze_task` — detect array relevance and operation type
- `analyze_context` — infer array shape, element type, fields
- `review_action` — review proposed tool calls for array-related risks
- `build_guidance` — produce compact guidance (<150 words)

Detected element types: `strings`, `numbers`, `booleans`,
`numbers_or_mixed`, `objects`.

Numerical array support: detects float/integer arrays, warns on division
risks, and provides precision guidance for statistical operations.

## AppVerifier

AppVerifier is a deterministic, zero-token plugin that verifies apps are
actually complete before allowing the agent to declare "done".

It translates user requests into concrete criteria (file existence + content
checks) and blocks premature completion claims by injecting feedback and
keeping the agent working until all criteria pass.

Supported patterns: Todo, CRUD, Calculator, Dashboard, Auth, E-commerce, Chat,
Data Visualization.

See `docs/usage_guide.md` for full documentation.

## DataExporter

DataExporter is a deterministic, zero-token plugin that collects successful
session trajectories from the EventLog and exports them as JSONL for
fine-tuning.

It reads `session.outcome` events and applies quality filters:
- Must have `outcome: "success"`
- No protected file violations
- Completed within `max_turns` (default: 20)
- No error or timeout events

### Export CLI

```bash
# Export successful sessions to JSONL
python main.py --profile lite --export-data --export-path finetune_data

# The export completes and exits — no interactive loop
```

Output format (`finetune_data/trajectories.jsonl`):
```json
{
  "session_id": "abc123",
  "app_type": "crud",
  "metadata": {"outcome": "success", "model_turns": 12, ...},
  "trajectory": [
    {"role": "user", "content": "Build a CRUD API..."},
    {"role": "assistant", "content": "", "tool_calls": [...]},
    {"role": "tool", "tool_name": "write_file", "content": "..."},
    ...
  ]
}
```

For continuous optimization, see `scripts/fine_tune.py`, `scripts/swap_model.py`,
and `scripts/optimize_loop.sh`.
