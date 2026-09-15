"""
Phase 3 Benchmark Report Generator
Partial-credit scoring + breakage attribution + degradation curves
"""

import json
import sqlite3
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
from datetime import datetime
import statistics


@dataclass
class StepMetrics:
    """Per-step metrics for breakage attribution"""
    step_id: int
    tool_name: str
    success: bool
    duration_ms: float
    token_cost: int
    error_type: Optional[str] = None
    recovery_attempts: int = 0
    is_recovery_step: bool = False
    dependency_ids: List[int] = field(default_factory=list)
    failure_mode: Optional[str] = None


@dataclass
class TrajectoryMetrics:
    """Per-trajectory metrics"""
    trajectory_id: str
    task_name: str
    horizon_length: int
    success: bool
    partial_credit: float
    total_steps: int
    total_tokens: int
    total_duration_ms: float
    abort_reason: Optional[str] = None
    recovery_count: int = 0
    recovery_latency_avg: float = 0.0
    cascade_rate: float = 0.0
    breakage_step: Optional[int] = None
    breakage_tool: Optional[str] = None
    breakage_type: Optional[str] = None
    prevented_failures: int = 0
    tool_calls_per_success: float = 0.0
    peak_memory_kb: int = 0
    failure_mode: Optional[str] = None
    steps: List[StepMetrics] = field(default_factory=list)
    verification: Optional[Dict[str, Any]] = None


@dataclass
class HorizonMetrics:
    """Metrics by horizon region"""
    region: str
    step_range: Tuple[int, int]
    n_trajectories: int
    success_rate: float
    partial_credit_avg: float
    avg_tokens: float
    avg_duration_ms: float


@dataclass
class BenchmarkReport:
    """Complete benchmark report"""
    timestamp: str
    git_commit: str
    total_trajectories: int
    success_rate: float
    partial_credit_avg: float
    abort_rate: float
    silent_failure_rate: float
    loop_rate: float
    invalid_call_rate: float
    recovery_efficiency: float
    cascade_rate: float
    avg_recovery_latency_steps: float
    avg_tokens_per_trajectory: float
    avg_duration_ms: float
    prevented_failures_total: int
    avg_tool_calls_per_success: float
    avg_peak_memory_kb: float
    failure_mode_distribution: Dict[str, int]
    by_horizon: List[HorizonMetrics]
    breakage_distribution: Dict[str, float]
    tool_failure_distribution: Dict[str, int]
    error_type_distribution: Dict[str, int]
    failure_mode_distribution: Dict[str, int]
    recovery_success_by_type: Dict[str, float]
    degradation_curve: List[Tuple[int, float]]
    trajectories: List[TrajectoryMetrics] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        lines = [
            f"# Benchmark Report: {self.timestamp}",
            f"**Git Commit:** `{self.git_commit}`",
            f"**Total Trajectories:** {self.total_trajectories}",
            "",
            "## Overall Metrics",
            f"| Metric | Value | Target | Status |",
            f"|--------|-------|--------|--------|",
            f"| Success Rate | {self.success_rate:.1%} | >80% | {'✅' if self.success_rate > 0.80 else '❌'} |",
            f"| Partial Credit Avg | {self.partial_credit_avg:.1%} | - | |",
            f"| Abort Rate | {self.abort_rate:.1%} | <10% | {'✅' if self.abort_rate < 0.10 else '❌'} |",
            f"| Silent Failure Rate | {self.silent_failure_rate:.1%} | <10% | {'✅' if self.silent_failure_rate < 0.10 else '❌'} |",
            f"| Loop Rate | {self.loop_rate:.1%} | <5% | {'✅' if self.loop_rate < 0.05 else '❌'} |",
            f"| Cascade Rate | {self.cascade_rate:.1%} | <5% | {'✅' if self.cascade_rate < 0.05 else '❌'} |",
            f"| Recovery Efficiency | {self.recovery_efficiency:.1%} | - | |",
            f"| Avg Peak Memory | {self.avg_peak_memory_kb:.0f} KB | - | |",
            "",
            "## By Horizon",
            "| Region | Steps | N | Success | Partial Credit |",
            "|--------|-------|----|---------|----------------|",
        ]
        for h in self.by_horizon:
            lines.append(
                f"| {h.region} | {h.step_range[0]}-{h.step_range[1]} | "
                f"{h.n_trajectories} | {h.success_rate:.1%} | {h.partial_credit_avg:.1%} |"
            )

        lines.extend([
            "",
            "## Breakage Distribution",
            "| Step Bucket | Failure Rate |",
            "|-------------|--------------|",
        ])
        for bucket, rate in sorted(self.breakage_distribution.items()):
            lines.append(f"| {bucket} | {rate:.1%} |")

        lines.extend([
            "",
            "## Tool Failure Distribution",
            "| Tool | Failure Count |",
            "|------|---------------|",
        ])
        for tool, count in sorted(self.tool_failure_distribution.items(), key=lambda x: -x[1]):
            lines.append(f"| {tool} | {count} |")

        if self.failure_mode_distribution:
            lines.extend([
                "",
                "## Failure Mode Distribution",
                "| Mode | Count |",
                "|------|-------|",
            ])
            for mode, count in sorted(self.failure_mode_distribution.items(), key=lambda x: -x[1]):
                lines.append(f"| {mode} | {count} |")

        return "\n".join(lines)


class BenchmarkAnalyzer:
    def __init__(self, db_path: str = "benchmark_results.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS benchmark_runs (
                run_id TEXT PRIMARY KEY,
                timestamp DATETIME,
                git_commit TEXT,
                task_name TEXT,
                trajectory_id TEXT,
                success BOOLEAN,
                partial_credit REAL,
                total_steps INTEGER,
                total_tokens INTEGER,
                total_duration_ms REAL,
                abort_reason TEXT,
                recovery_count INTEGER,
                cascade_rate REAL,
                breakage_step INTEGER,
                breakage_tool TEXT,
                breakage_type TEXT,
                prevented_failures INTEGER,
                tool_calls_per_success REAL,
                horizon_bucket TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS benchmark_steps (
                step_id INTEGER PRIMARY KEY AUTOINCREMENT,
                trajectory_id TEXT,
                step_index INTEGER,
                tool_name TEXT,
                success BOOLEAN,
                duration_ms REAL,
                token_cost INTEGER,
                error_type TEXT,
                recovery_attempts INTEGER,
                is_recovery_step BOOLEAN,
                dependency_ids TEXT
            )
        """)
        self.conn.commit()

    def record_trajectory(self, trajectory: TrajectoryMetrics):
        cursor = self.conn.cursor()
        horizon_bucket = self._get_horizon_bucket(trajectory.horizon_length)
        cursor.execute("""
            INSERT OR REPLACE INTO benchmark_runs (
                run_id, timestamp, git_commit, task_name, trajectory_id,
                success, partial_credit, total_steps, total_tokens, total_duration_ms,
                abort_reason, recovery_count, cascade_rate, breakage_step, breakage_tool,
                breakage_type, prevented_failures, tool_calls_per_success, horizon_bucket
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f"{trajectory.trajectory_id}_{datetime.now().isoformat()}",
            datetime.now().isoformat(),
            self._get_git_commit(),
            trajectory.task_name,
            trajectory.trajectory_id,
            trajectory.success,
            trajectory.partial_credit,
            trajectory.total_steps,
            trajectory.total_tokens,
            trajectory.total_duration_ms,
            trajectory.abort_reason,
            trajectory.recovery_count,
            trajectory.cascade_rate,
            trajectory.breakage_step,
            trajectory.breakage_tool,
            trajectory.breakage_type,
            trajectory.prevented_failures,
            trajectory.tool_calls_per_success,
            horizon_bucket
        ))

        for step in trajectory.steps:
            cursor.execute("""
                INSERT INTO benchmark_steps (
                    trajectory_id, step_index, tool_name, success,
                    duration_ms, token_cost, error_type,
                    recovery_attempts, is_recovery_step, dependency_ids
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trajectory.trajectory_id,
                step.step_id,
                step.tool_name,
                step.success,
                step.duration_ms,
                step.token_cost,
                step.error_type,
                step.recovery_attempts,
                step.is_recovery_step,
                json.dumps(step.dependency_ids)
            ))

        self.conn.commit()

    def generate_report(self, run_id: Optional[str] = None) -> BenchmarkReport:
        cursor = self.conn.cursor()
        if run_id:
            cursor.execute("SELECT * FROM benchmark_runs WHERE run_id = ?", (run_id,))
        else:
            cursor.execute("SELECT * FROM benchmark_runs ORDER BY timestamp DESC LIMIT 100")
        rows = cursor.fetchall()
        trajectories = [self._row_to_trajectory(row) for row in rows]
        if not trajectories:
            raise ValueError("No trajectories found for report generation")
        return self._compute_metrics(trajectories)

    def compare_reports(self, report_a: BenchmarkReport, report_b: BenchmarkReport) -> str:
        lines = [
            "# Benchmark Regression Report",
            "",
            "## Summary",
            f"| Metric | {report_a.timestamp[:10]} | {report_b.timestamp[:10]} | Change | Status |",
            "|--------|---------|---------|--------|--------|",
        ]

        metrics = [
            ("Success Rate", report_a.success_rate, report_b.success_rate, 0.80),
            ("Partial Credit Avg", report_a.partial_credit_avg, report_b.partial_credit_avg, 0.00),
            ("Abort Rate", report_a.abort_rate, report_b.abort_rate, 0.10, True),
            ("Cascade Rate", report_a.cascade_rate, report_b.cascade_rate, 0.05, True),
            ("Recovery Efficiency", report_a.recovery_efficiency, report_b.recovery_efficiency, 0.00),
            ("Avg Tokens", report_a.avg_tokens_per_trajectory, report_b.avg_tokens_per_trajectory, 0.00),
        ]

        for metric, val_a, val_b, threshold, *is_neg in metrics:
            is_neg = is_neg[0] if is_neg else False
            change = val_b - val_a
            change_str = f"{change:+.1%}" if isinstance(val_a, float) else f"{change:+.0f}"
            if is_neg:
                good = change < 0
                status = "✅" if good else "⚠️" if abs(change) > 0.05 else "➖"
            else:
                good = change > 0
                status = "✅" if good else "⚠️" if abs(change) > 0.05 else "➖"

            if isinstance(val_a, float):
                lines.append(f"| {metric} | {val_a:.1%} | {val_b:.1%} | {change_str} | {status} |")
            else:
                lines.append(f"| {metric} | {val_a:.0f} | {val_b:.0f} | {change_str} | {status} |")

        lines.extend([
            "",
            "## Horizon Breakdown (Change)",
            "| Region | Old Success | New Success | Change |",
            "|--------|-------------|-------------|--------|",
        ])

        horizons_a = {h.region: h for h in report_a.by_horizon}
        horizons_b = {h.region: h for h in report_b.by_horizon}

        for region in horizons_a.keys() & horizons_b.keys():
            h_a = horizons_a[region]
            h_b = horizons_b[region]
            change = h_b.success_rate - h_a.success_rate
            lines.append(
                f"| {region} | {h_a.success_rate:.1%} | {h_b.success_rate:.1%} | {change:+.1%} |"
            )

        lines.extend([
            "",
            "## Degradation Curve",
            "```",
            "Step Bucket | Old Success | New Success",
            "------------|-------------|-------------",
        ])

        for i in range(min(len(report_a.degradation_curve), len(report_b.degradation_curve))):
            step_a, val_a = report_a.degradation_curve[i]
            step_b, val_b = report_b.degradation_curve[i]
            lines.append(f"  {step_a}-{step_a+10}    | {val_a:.1%}       | {val_b:.1%}")

        lines.append("```")
        return "\n".join(lines)

    def _get_horizon_bucket(self, steps: int) -> str:
        if steps <= 20:
            return "short"
        elif steps <= 50:
            return "medium"
        else:
            return "long"

    def _get_git_commit(self) -> str:
        import subprocess
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()[:8]
        except Exception:
            return "unknown"

    def _row_to_trajectory(self, row) -> TrajectoryMetrics:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM benchmark_steps WHERE trajectory_id = ? ORDER BY step_index
        """, (row['trajectory_id'],))
        step_rows = cursor.fetchall()
        steps = []
        for sr in step_rows:
            steps.append(StepMetrics(
                step_id=sr['step_index'],
                tool_name=sr['tool_name'],
                success=bool(sr['success']),
                duration_ms=sr['duration_ms'],
                token_cost=sr['token_cost'],
                error_type=sr['error_type'],
                recovery_attempts=sr['recovery_attempts'],
                is_recovery_step=bool(sr['is_recovery_step']),
                dependency_ids=json.loads(sr['dependency_ids']) if sr['dependency_ids'] else []
            ))

        return TrajectoryMetrics(
            trajectory_id=row['trajectory_id'],
            task_name=row['task_name'],
            horizon_length=row['total_steps'],
            success=bool(row['success']),
            partial_credit=row['partial_credit'],
            total_steps=row['total_steps'],
            total_tokens=row['total_tokens'],
            total_duration_ms=row['total_duration_ms'],
            abort_reason=row['abort_reason'],
            recovery_count=row['recovery_count'],
            recovery_latency_avg=0.0,
            cascade_rate=row['cascade_rate'],
            breakage_step=row['breakage_step'],
            breakage_tool=row['breakage_tool'],
            breakage_type=row['breakage_type'],
            prevented_failures=row['prevented_failures'],
            tool_calls_per_success=row['tool_calls_per_success'],
            steps=steps
        )

    def _compute_metrics(self, trajectories: List[TrajectoryMetrics]) -> BenchmarkReport:
        n = len(trajectories)
        successes = [t for t in trajectories if t.success]
        aborts = [t for t in trajectories if t.abort_reason is not None]
        silent_failures = [t for t in trajectories if not t.success and not t.abort_reason]

        success_rate = len(successes) / n if n > 0 else 0
        partial_credit_avg = statistics.mean([t.partial_credit for t in trajectories]) if n > 0 else 0
        abort_rate = len(aborts) / n if n > 0 else 0
        silent_failure_rate = len(silent_failures) / n if n > 0 else 0

        total_recoveries = sum(t.recovery_count for t in trajectories)
        total_trajectories_with_recovery = len([t for t in trajectories if t.recovery_count > 0])
        recovery_success_count = sum(
            1 for t in trajectories if t.recovery_count > 0 and t.success
        )
        recovery_efficiency = (
            recovery_success_count / total_trajectories_with_recovery
            if total_trajectories_with_recovery > 0 else 0
        )

        cascade_rate = statistics.mean([t.cascade_rate for t in trajectories]) if n > 0 else 0
        recovery_latencies = [t.recovery_latency_avg for t in trajectories if t.recovery_latency_avg > 0]
        avg_recovery_latency = statistics.mean(recovery_latencies) if recovery_latencies else 0

        avg_tokens = statistics.mean([t.total_tokens for t in trajectories]) if n > 0 else 0
        avg_duration = statistics.mean([t.total_duration_ms for t in trajectories]) if n > 0 else 0
        prevented_failures_total = sum(t.prevented_failures for t in trajectories)
        tool_calls_per_success = [t.tool_calls_per_success for t in trajectories if t.tool_calls_per_success > 0]
        avg_tool_calls_per_success = statistics.mean(tool_calls_per_success) if tool_calls_per_success else 0
        peak_memory_kbs = [t.peak_memory_kb for t in trajectories if t.peak_memory_kb > 0]
        avg_peak_memory_kb = statistics.mean(peak_memory_kbs) if peak_memory_kbs else 0

        loop_count = 0
        invalid_call_count = 0
        for t in trajectories:
            seen = set()
            for step in t.steps:
                key = f"{step.tool_name}:{step.step_id}"
                if key in seen:
                    loop_count += 1
                seen.add(key)

        total_steps = sum(t.total_steps for t in trajectories)
        loop_rate = loop_count / total_steps if total_steps > 0 else 0
        invalid_call_rate = invalid_call_count / total_steps if total_steps > 0 else 0

        horizon_buckets = defaultdict(list)
        for t in trajectories:
            bucket = self._get_horizon_bucket(t.horizon_length)
            horizon_buckets[bucket].append(t)

        by_horizon = []
        for region, trajs in horizon_buckets.items():
            step_range = self._get_step_range(region)
            by_horizon.append(HorizonMetrics(
                region=region,
                step_range=step_range,
                n_trajectories=len(trajs),
                success_rate=sum(1 for t in trajs if t.success) / len(trajs) if trajs else 0,
                partial_credit_avg=statistics.mean([t.partial_credit for t in trajs]) if trajs else 0,
                avg_tokens=statistics.mean([t.total_tokens for t in trajs]) if trajs else 0,
                avg_duration_ms=statistics.mean([t.total_duration_ms for t in trajs]) if trajs else 0
            ))

        breakage_distribution = defaultdict(float)
        for t in trajectories:
            if t.breakage_step is not None:
                bucket = self._get_breakage_bucket(t.breakage_step)
                breakage_distribution[bucket] += 1
        for bucket in breakage_distribution:
            breakage_distribution[bucket] /= n

        tool_failure_distribution = defaultdict(int)
        for t in trajectories:
            for step in t.steps:
                if not step.success:
                    tool_failure_distribution[step.tool_name] += 1

        error_type_distribution = defaultdict(int)
        for t in trajectories:
            for step in t.steps:
                if step.error_type:
                    error_type_distribution[step.error_type] += 1

        failure_mode_distribution = defaultdict(int)
        for t in trajectories:
            if not t.success and t.failure_mode:
                failure_mode_distribution[t.failure_mode] += 1
            for step in t.steps:
                if not step.success and step.failure_mode:
                    failure_mode_distribution[step.failure_mode] += 1

        recovery_success_by_type = {}

        degradation_curve = []
        max_steps = max([t.total_steps for t in trajectories]) if trajectories else 0
        for i in range(0, max_steps, 10):
            cumulative_success = 0
            count = 0
            for t in trajectories:
                if t.total_steps >= i:
                    completed_steps = sum(1 for s in t.steps if s.success)
                    cumulative_success += completed_steps / max(1, t.total_steps)
                    count += 1
            if count > 0:
                degradation_curve.append((i, cumulative_success / count))

        return BenchmarkReport(
            timestamp=datetime.now().isoformat(),
            git_commit=self._get_git_commit(),
            total_trajectories=n,
            success_rate=success_rate,
            partial_credit_avg=partial_credit_avg,
            abort_rate=abort_rate,
            silent_failure_rate=silent_failure_rate,
            loop_rate=loop_rate,
            invalid_call_rate=invalid_call_rate,
            recovery_efficiency=recovery_efficiency,
            cascade_rate=cascade_rate,
            avg_recovery_latency_steps=avg_recovery_latency,
            avg_tokens_per_trajectory=avg_tokens,
            avg_duration_ms=avg_duration,
            prevented_failures_total=prevented_failures_total,
            avg_tool_calls_per_success=avg_tool_calls_per_success,
            avg_peak_memory_kb=avg_peak_memory_kb,
            by_horizon=by_horizon,
            breakage_distribution=dict(breakage_distribution),
            tool_failure_distribution=dict(tool_failure_distribution),
            error_type_distribution=dict(error_type_distribution),
            failure_mode_distribution=dict(failure_mode_distribution),
            recovery_success_by_type=recovery_success_by_type,
            degradation_curve=degradation_curve,
            trajectories=trajectories
        )

    def _get_step_range(self, region: str) -> Tuple[int, int]:
        ranges = {
            "short": (0, 20),
            "medium": (21, 50),
            "long": (51, 100)
        }
        return ranges.get(region, (0, 100))

    def _get_breakage_bucket(self, step: int) -> str:
        if step <= 10:
            return "step_0_10"
        elif step <= 30:
            return "step_11_30"
        elif step <= 60:
            return "step_31_60"
        else:
            return "step_61_plus"
