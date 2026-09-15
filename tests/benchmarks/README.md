# Benchmark Suite

The benchmark suite measures ArrayHelper's impact on array-processing tasks.
It runs each task with the helper enabled and disabled, comparing completion
rates, model turns, tool calls, and token overhead.

## Location

- `tests/benchmarks/tasks.py` — task definitions (10 array tasks)
- `tests/benchmarks/runner.py` — `BenchmarkModel`, `BenchmarkResult`,
  `run_task()`, `run_benchmark_suite()`
- `tests/benchmarks/test_array_benchmarks.py` — pytest tests

## Task categories

| Category   | Tags          | Description                          |
|------------|---------------|--------------------------------------|
| Filter     | `filter`      | Filter items by a property           |
| Sort       | `sort`        | Sort items (with stability notes)    |
| Update     | `update`      | Update records by ID                 |
| Delete     | `delete`      | Delete records by ID                 |
| Aggregate  | `aggregate`   | Sum, count, average                  |
| Find       | `find`        | Search for an item by property       |

Each task includes a verification function that checks the resulting file
content deterministically (no model calls needed for verification).

## Running benchmarks

```powershell
# Run all benchmark tests
python -m pytest tests/benchmarks/ -v

# Run the suite programmatically
python -c "
from tests.benchmarks.tasks import ALL_ARRAY_TASKS
from tests.benchmarks.runner import run_benchmark_suite
report = run_benchmark_suite(ALL_ARRAY_TASKS, runs_per_task=1)
print(json.dumps(report, indent=2))
"
```

## Metrics

- `completed` — whether the task verification passed
- `model_turns` — number of model API calls
- `tool_calls` — number of tool invocations (from event log)
- `prompt_injections` — count of injected context messages
- `token_overhead_estimate` — word count of `[array context]` injections
- `error` — error string if the run failed

## Failure recovery tests

`tests/failure_recovery/test_array_failures.py` tests array tasks with:
- Tool timeouts (retry recovery)
- Malformed arguments (arg repair recovery)
- Silent wrong outputs (graceful handling)
- Budget exhaustion (ToolError on max retries)
- Compound faults (timeout + malformed simultaneously)
- Empty collection edge cases
