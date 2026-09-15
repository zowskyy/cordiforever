from __future__ import annotations

import argparse
from pathlib import Path

from core.context import Context
from core.calibration import resolve_calibration
from core.registry import PluginRegistry
from plugins.agent.loop import AgentLoop
from plugins.agent.semantic_router import SemanticRouter
from plugins.agent.parameter_extractor import ParameterExtractor
from plugins.agent.query_splitter import QuerySplitter
from plugins.agent.multi_domain_router import MultiDomainRouter
from plugins.agent.aggregate_response import AggregateResponse
from plugins.agent.schema_router import SchemaRouter
from plugins.agent.array_helper import ArrayHelper
from plugins.agent.app_verifier import AppVerifier
from plugins.core.event_logger import EventLogger
from plugins.core.data_exporter import DataExporter
from plugins.core.persona_memory import PersonaMemoryPlugin
from plugins.core.lifecycle import LifecycleConsolidatorPlugin
from plugins.core.telemetry import TelemetryPlugin
from plugins.core.context_builder import ContextBuilderPlugin
from plugins.core.context_pruner import ContextPrunerPlugin
from plugins.core.error_recovery import ErrorRecoveryPlugin
from plugins.core.health_monitoring import HealthMonitoringPlugin
from plugins.core.metrics import MetricsPlugin
from plugins.core.tracing import TracingPlugin
from plugins.core.formal_contracts import FormalContractsPlugin
from plugins.core.hot_swap import HotSwapPlugin
from plugins.core.semantic_memory import SemanticMemoryPlugin
from plugins.core.episodic_memory import EpisodicMemoryPlugin
from plugins.core.closed_loop import ClosedLoopRetrievalPlugin
from plugins.core.reality_projector import RealityProjectorPlugin
from plugins.core.recovery_manager import RecoveryManagerPlugin
from plugins.core.config_validation import ConfigValidationPlugin
from plugins.core.linting import LintingPlugin
from plugins.core.logic_layer import LogicLayerPlugin
from plugins.core.intent_router import IntentRouterPlugin
from plugins.core.summarizer import SummarizerPlugin
from plugins.core.deterministic_knowledge import DeterministicKnowledgeStore
from plugins.core.batch_cache import BatchCache
from plugins.core.decision_logger import DecisionLogger
from plugins.core.tool_result_pruner import ToolResultPruner
from plugins.web.server import WebDashboard
from plugins.ci.ci_plugin import CIPlugin
from plugins.math.router import MathRouterPlugin
from plugins.math.symbolic_engine import SymbolicEnginePlugin
from plugins.math.verifier import MathVerifierPlugin
from plugins.math.pipeline import MathPipelinePlugin
from plugins.math.datetime_router import DateTimeRouterPlugin
from plugins.math.datetime_engine import DateTimeEnginePlugin
from plugins.math.units_router import UnitsRouterPlugin
from plugins.math.units_engine import UnitsEnginePlugin
from plugins.model.ollama import OllamaModel
from plugins.model.embedding import EmbeddingModel
from plugins.parsers.tool_call_parser import OllamaToolCallParser
from plugins.tools.file import FileTools
from plugins.tools.asgi_wsgi_tester import ASGIWSGITester
from plugins.tools.run_command import RunCommand
from plugins.ui.terminal import TerminalUI


def build_application(workspace: Path, model_name: str, ollama_url: str, db_path: Path, profile: str = "lite", enable_semantic_router: bool = False, compact_schema: bool = False, calibration_overrides: dict | None = None):
    """
    P2 FIX: Lite vs Full profile.
    - lite (default): 24 plugins (zero-token). Saves tokens for 1.5B via compact schema,
      file tools, array helper, dry completions, server testing, and single pruner. Zero-token.
    - full: 47 plugins (adds observability/memory/debugging). Semantic router gated even here.

    Per-model numbers (pruner budget, message cap, ...) are NOT literals in the
    invariant layer: they resolve from the model calibration table
    (core.context.MODEL_PRESETS) and ride along in Context.config["calibration"].
    """
    # Resolve per-model calibration (table in core.context) so loop/pruner read
    # it from config. Explicit config overrides possible via resolve_calibration.
    calibration = resolve_calibration(model_name, calibration_overrides)
    # SchemaRouter is always registered but compact mode is profile-dependent.
    # lite: compact_schema=True (saves tokens for 1.5B). full: verbose by default.
    schema_enabled = True
    # Constrained decoding emits the compact action format, so it needs compact mode in every profile.
    schema_compact = compact_schema or (profile == "lite") or bool(calibration.get("constrained_actions"))
    # Pass semantic flag via context config so SemanticRouter and loop can gate
    ctx = Context(config={
        "workspace": str(workspace.resolve()),
        "model": model_name,
        "ollama_url": ollama_url,
        "profile": profile,
        "semantic_router_enabled": enable_semantic_router,
        "schema_router_enabled": schema_enabled,
        "compact_schema": schema_compact,
        "calibration": calibration,
    })
    reg = PluginRegistry(ctx)

    plugin_config = {
        "event_logger": {"db_path": db_path},
        "ollama_model": {"model": model_name, "base_url": ollama_url, "options": calibration.get("sampling"),
                         "text_tool_protocol": bool(calibration.get("text_tool_protocol", False))},
        "file_tools": {"workspace": workspace},
    }

    # === LITE CORE: 24 plugins total ===
    # Event log: EventLogger, DataExporter
    # Model + parser: OllamaModel, OllamaToolCallParser
    # Tools: FileTools, ASGIWSGITester
    # Deterministic pool (8): MathRouter, SymbolicEngine, MathVerifier, MathPipeline,
    #                         DateTimeRouter, DateTimeEngine, UnitsRouter, UnitsEngine
    # Routing layer (4): ParameterExtractor, QuerySplitter, MultiDomainRouter, AggregateResponse
    # SchemaRouter: compact tool schema (deterministic, zero-token)
    # ArrayHelper + AppVerifier + ASGIWSGITester: deterministic reasoning & verification (zero-token)
    # Pruner + loop + UI: ContextPrunerPlugin, AgentLoop, TerminalUI, DataExporter
    reg.register(EventLogger(db_path))
    reg.register(OllamaModel(**plugin_config["ollama_model"]))
    reg.register(FileTools(workspace))
    reg.register(OllamaToolCallParser())
    # Deterministic pool (zero-token)
    reg.register(MathRouterPlugin())
    reg.register(SymbolicEnginePlugin())
    reg.register(MathVerifierPlugin())
    reg.register(MathPipelinePlugin())
    reg.register(DateTimeRouterPlugin())
    reg.register(DateTimeEnginePlugin())
    reg.register(UnitsRouterPlugin())
    reg.register(UnitsEnginePlugin())
    # Routing layer
    reg.register(ParameterExtractor())
    reg.register(QuerySplitter())
    reg.register(MultiDomainRouter())
    reg.register(AggregateResponse())
    # Compact schema router (deterministic, zero-token — no model calls)
    reg.register(SchemaRouter())
    # Optional array reasoning capability (deterministic, zero-token)
    reg.register(ArrayHelper())
    # ASGI/WSGI server tester (deterministic, zero-token — only activates when invoked)
    reg.register(ASGIWSGITester())
    # App completion verifier — deterministic artifact checks (zero-token when not relevant)
    reg.register(AppVerifier())
    # Single pruner (30k budget for 33k ctx) — needed even in lite
    reg.register(ContextPrunerPlugin())
    # Deterministic knowledge store (zero-token TF-IDF, lite-safe)
    reg.register(DeterministicKnowledgeStore())
    # Batch cache (zero-token content-hash memoization, lite-safe)
    reg.register(BatchCache())
    # Decision logger (zero-token JSONL logging for routing and tool decisions)
    reg.register(DecisionLogger())
    # Tool result pruner (zero-token compaction/spill for oversized tool results)
    reg.register(ToolResultPruner())
    # Core loop + data export for fine-tuning (zero-token, deterministic)
    reg.register(AgentLoop())
    reg.register(DataExporter())
    reg.register(TerminalUI())
    reg.register(WebDashboard())
    # Lightweight metrics (zero-token, event-driven) — safe for lite
    reg.register(MetricsPlugin())
    # Sandboxed command execution (zero-token, cwd-restricted)
    reg.register(RunCommand(workspace=workspace))

    if profile == "full":
        # Observability / extended memory — only in full
        reg.register(EmbeddingModel())
        # Semantic router gated: only enabled if flag set
        reg.register(SemanticRouter(enabled=enable_semantic_router))
        reg.register(HealthMonitoringPlugin())
        reg.register(LintingPlugin())
        reg.register(IntentRouterPlugin())
        reg.register(LogicLayerPlugin())
        reg.register(TracingPlugin())
        reg.register(PersonaMemoryPlugin())
        reg.register(LifecycleConsolidatorPlugin())
        reg.register(TelemetryPlugin())
        reg.register(SemanticMemoryPlugin())
        reg.register(EpisodicMemoryPlugin())
        reg.register(RealityProjectorPlugin())
        reg.register(RecoveryManagerPlugin())
        reg.register(SummarizerPlugin())
        reg.register(ErrorRecoveryPlugin())
        reg.register(FormalContractsPlugin())
        reg.register(HotSwapPlugin())
        reg.register(ClosedLoopRetrievalPlugin())
        reg.register(ContextBuilderPlugin())
        reg.register(ConfigValidationPlugin())
        reg.register(CIPlugin())
    else:
        # lite: still provide minimal health/metrics via loop internals, but don't register heavy plugins
        # Semantic router not registered in lite at all — zero embedding cost
        pass

    if calibration.get("constrained_actions") and schema_compact:
        ctx.plugins["ollama_model"].response_format = ctx.plugins["schema_router"].get_response_format()

    expected_lite = 31
    expected_full = 53
    actual = len(ctx.plugins)
    if profile == "lite":
        assert actual == expected_lite, f"Lite profile: expected {expected_lite} plugins, got {actual}"
        assert "semantic_router" not in ctx.plugins, "SemanticRouter registered in lite profile"
        assert "schema_router" in ctx.plugins, "SchemaRouter should be registered in lite"
        assert ctx.plugins["schema_router"].enabled is True, "SchemaRouter should be enabled in lite"
        assert ctx.plugins["schema_router"].compact_mode is True, "SchemaRouter compact_mode should be True in lite"
        assert "array_helper" in ctx.plugins, "ArrayHelper should be registered in lite"
        assert "app_verifier" in ctx.plugins, "AppVerifier should be registered in lite"
        assert "data_exporter" in ctx.plugins, "DataExporter should be registered in lite"
        assert "asgi_wsgi_tester" in ctx.plugins, "ASGIWSGITester should be registered in lite"
        assert "deterministic_knowledge" in ctx.plugins, "DeterministicKnowledgeStore should be registered in lite"
        assert "batch_cache" in ctx.plugins, "BatchCache should be registered in lite"
        assert "decision_logger" in ctx.plugins, "DecisionLogger should be registered in lite"
        assert "web_dashboard" in ctx.plugins, "WebDashboard should be registered in lite"
        assert "tool_result_pruner" in ctx.plugins, "ToolResultPruner should be registered in lite"
        assert "metrics" in ctx.plugins, "MetricsPlugin should be registered in lite"
        assert "run_command" in ctx.plugins, "RunCommand should be registered in lite"
    elif profile == "full":
        assert actual == expected_full, f"Full profile: expected {expected_full}plugins, got {actual}"
        assert "schema_router" in ctx.plugins, "SchemaRouter should be registered in full"
        assert "app_verifier" in ctx.plugins, "AppVerifier should be registered in full"
        assert "data_exporter" in ctx.plugins, "DataExporter should be registered in full"
        assert "asgi_wsgi_tester" in ctx.plugins, "ASGIWSGITester should be registered in full"
        assert "array_helper" in ctx.plugins, "ArrayHelper should be registered in full"
        assert "deterministic_knowledge" in ctx.plugins, "DeterministicKnowledgeStore should be registered in full"
        assert "batch_cache" in ctx.plugins, "BatchCache should be registered in full"
        assert "decision_logger" in ctx.plugins, "DecisionLogger should be registered in full"
        assert "web_dashboard" in ctx.plugins, "WebDashboard should be registered in full"
        assert "tool_result_pruner" in ctx.plugins, "ToolResultPruner should be registered in full"
        assert "metrics" in ctx.plugins, "MetricsPlugin should be registered in full"
        assert "run_command" in ctx.plugins, "RunCommand should be registered in full"
        if enable_semantic_router:
            assert ctx.plugins["semantic_router"].enabled is True, "SemanticRouter should be enabled"
        else:
            assert ctx.plugins["semantic_router"].enabled is False, "SemanticRouter should be disabled"

    print(f"[startup] profile={profile}, plugins={actual}, model={model_name}, semantic_router={enable_semantic_router}, compact_schema={schema_compact}")

    reg.start_all()
    return ctx, reg


def main() -> int:
    p = argparse.ArgumentParser(description="Cordis-Lite local coding agent (cordiiv2)")
    p.add_argument("--workspace", default="workspace", help="Workspace directory")
    p.add_argument("--model", default="gemma3:1b", help="Ollama model name")
    p.add_argument("--ollama-url", default="http://127.0.0.1:11434", help="Ollama base URL")
    p.add_argument("--db", default="continuity/continuity.db", help="SQLite event log path")
    p.add_argument("--profile", default="lite", choices=["lite", "full"], help="lite=24 plugins (default, saves tokens), full=47 plugins (debug)")
    p.add_argument("--enable-semantic-router", action="store_true", help="Enable semantic router (embedding cost, off by default)")
    p.add_argument("--compact-schema", action="store_true", help="Enable compact tool schema (single call_tool interface, saves tokens)")
    p.add_argument("--dry-run", action="store_true", help="Build app, assert invariants, and exit without running UI")
    p.add_argument("--export-data", action="store_true", help="Export successful session trajectories to JSONL for fine-tuning")
    p.add_argument("--export-path", default="finetune_data", help="Directory for exported training data (default: finetune_data)")
    args = p.parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve()
    ctx, reg = build_application(workspace, args.model, args.ollama_url, db_path, profile=args.profile, enable_semantic_router=args.enable_semantic_router, compact_schema=args.compact_schema)
    if args.dry_run:
        print(f"Dry run OK: profile={args.profile}, plugins={len(ctx.plugins)}")
        reg.stop_all()
        return 0

    if args.export_data:
        exporter = ctx.plugins.get("data_exporter")
        if exporter is None:
            print("DataExporter not found in context")
            reg.stop_all()
            return 1
        export_dir = Path(args.export_path).expanduser().resolve()
        count = exporter.export_successful_sessions(export_dir)
        print(f"[export] Exported {count} successful session trajectories to {export_dir}")
        # Print first 5 file paths for verification
        exported_files = sorted(export_dir.glob("*.jsonl"))[:5]
        for f in exported_files:
            print(f"  - {f}")
        reg.stop_all()
        return 0
    try:
        ctx.plugins["terminal_ui"].run()
    finally:
        reg.stop_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
