# Cordi v2

**A multi-profile agent/plugin system for reliable operation under constrained local models.**

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-586%20passed-success)](https://github.com/zowskyy/cordii/actions)
[![Ollama](https://img.shields.io/badge/Ollama-1.5B%20ready-green)](https://ollama.ai)

> **Primary design target:** `gemma3:1b` (no native tool calling; tool use via text JSON) | **Context window:** 32768 tokens

---

## Quick Start

```bash
# Clone the repository
git clone https://github.com/zowskyy/cordii.git
cd cordii

# Install dependencies
pip install -r requirements.txt

# Run dry-run validation (no model required)
python main.py --dry-run

# Start the agent with Ollama
python main.py --model gemma3:1b
```

**Prerequisites:** Python 3.12+, [Ollama](https://ollama.ai) running locally with `gemma3:1b` pulled.

---

## Why Cordi v2?

Existing agent frameworks are designed for large cloud models with unlimited context. Cordi v2 is engineered from first principles for **constrained local models**:

| Problem | Cordi v2 Solution |
|---------|-------------------|
| 1.5B models can't handle long system prompts | Compact schema router + 3000-token pruner budget |
| Context window overflow | Single-pruner architecture preserving tool-call messages |
| Token waste from verbose tool schemas | Deterministic `SchemaRouter` with compact mode |
| No visibility into agent decisions | `DecisionLogger` + `EventLog` hash chain + web dashboard |
| Unpredictable token costs | Calibration table drives all per-model limits |

---

## Features

| Feature | Description | Profile |
|---------|-------------|---------|
| **Dual profiles** | `lite` (31 plugins, zero-token) and `full` (53 plugins, observability) | Both |
| **Compact schema routing** | Deterministic tool schema compression for 1.5B efficiency | Lite |
| **Event log hash chain** | Immutable SQLite audit trail with SHA-256 verification | Both |
| **Web dashboard** | Real-time SSE dashboard with session management | Both |
| **Tool result pruning** | Threshold/head/tail compaction + spill-to-disk | Both |
| **Decision logging** | JSONL routing/tool decision logs for fine-tuning | Both |
| **Sandboxed tools** | Workspace-restricted file tools + command execution | Both |
| **Semantic router** | Gated embedding-based routing (full profile only) | Full |
| **Export pipeline** | Session ZIP export + delta export + trajectory JSONL | Both |

---

## Architecture

```
Cordi v2
├── Core Kernel
│   ├── PluginRegistry (dependency-aware topological sort)
│   ├── EventLog (SQLite + hash chain)
│   ├── Context (calibration-driven config)
│   └── Metrics / Health / DecisionLogger
├── Agent Loop
│   ├── AgentLoop (orchestration + tool dispatch)
│   ├── SchemaRouter (compact/verbose modes)
│   ├── SpecializedRouters (math/datetime/units/repair)
│   └── ContextPruner (single-pass token/message enforcement)
├── Tools
│   ├── FileTools (read/write/delete/list/search)
│   ├── RunCommand (sandboxed subprocess)
│   └── ASGIWSGITester (endpoint verification)
└── Web UI
    └── FastAPI + SSE dashboard
```

### Plugin Count by Profile

| Profile | Plugins | Token Cost | Use Case |
|---------|---------|------------|----------|
| `lite` | 31 | 0 (zero-token) | Default, 1.5B production |
| `full` | 53 | Higher | Debug, observability, research |

---

## Configuration

### Model Calibration

All per-model limits are defined in `core/context.py` and resolved at startup:

```python
from core.calibration import resolve_calibration

cal = resolve_calibration("qwen2.5-coder:1.5b")
# {"pruner_budget": 30000, "max_messages": ..., "max_tool_result_bytes": ...}
```

### CLI Flags

```bash
python main.py --workspace ./workspace --model qwen2.5-coder:1.5b \
  --ollama-url http://127.0.0.1:11434 \
  --db continuity/continuity.db \
  --profile lite \
  --enable-semantic-router \
  --compact-schema \
  --export-data
```

| Flag | Default | Description |
|------|---------|-------------|
| `--workspace` | `workspace` | Workspace directory |
| `--model` | `qwen2.5-coder:1.5b` | Ollama model name |
| `--ollama-url` | `http://127.0.0.1:11434` | Ollama base URL |
| `--db` | `continuity/continuity.db` | SQLite event log path |
| `--profile` | `lite` | `lite` or `full` |
| `--enable-semantic-router` | `False` | Enable embedding-based routing |
| `--compact-schema` | `False` | Force compact tool schema |
| `--dry-run` | `False` | Build app, assert invariants, exit |
| `--export-data` | `False` | Export successful sessions to JSONL |

---

## Development

### Running Tests

```bash
# Full test suite (Windows)
pytest --basetemp C:\tmp\pytest_cordiiv2 -q

# Specific test file
pytest --basetemp C:\tmp\pytest_cordiiv2 tests/test_files.py -v

# Security gate
python scripts/verify_plugin_security.py
```

### Project Structure

```
cubic-stealer-20260830-2203/
├── main.py                    # Entrypoint + profile wiring
├── core/                      # Kernel invariants
│   ├── context.py             # Calibration + config
│   ├── event_log.py           # SQLite + hash chain
│   ├── events.py              # Event types + dataclasses
│   ├── registry.py            # Plugin registry + topological sort
│   └── ...
├── plugins/
│   ├── agent/                 # AgentLoop + routers
│   ├── core/                  # Metrics, DecisionLogger, ToolResultPruner
│   ├── model/                 # Ollama + embedding
│   ├── tools/                 # FileTools, RunCommand, ASGIWSGITester
│   └── web/                   # FastAPI dashboard
├── tests/                     # pytest suite (586 tests)
├── scripts/                   # Launch + verification scripts
└── knowledge/                 # Trajectory data for fine-tuning
```

---

## Documentation

- **[Architecture Overview](docs/)** — Detailed design documents
- **[Trajectory Summary](knowledge/TRAJECTORY_SUMMARY.md)** — Implementation history
- **[Chat Trajectories](knowledge/chat_trajectories.jsonl)** — Training data export

---

## Contributing

Contributions are welcome! Please see **[CONTRIBUTING.md](CONTRIBUTING.md)** for guidelines.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- Built for the **1.5B local model** design target
- Inspired by [deepseek-harness](https://github.com/deepseek-ai) patterns
- Event system and hash chain integrity modeled on distributed systems principles

---

<p align="center">
  Built with ❤️ for the local AI community
</p>
