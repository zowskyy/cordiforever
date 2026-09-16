"""Shared synthetic MV-02 fixtures: injected runners only (no real child, no monitor, no timing)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.monitor_validity_v2 import child_b_reference as child_b  # noqa: E402
from scripts.monitor_validity_v2 import mv02a_perturbation as ma  # noqa: E402

MIB = 1024 * 1024


class SyntheticB:
    """Injected monitor runner: writes the sidecar the real child would write, and returns monitor samples."""

    def __init__(self, *, a0_mib=4096, offset=0, capture=1.0, gap=0.25, wrong_parent=False,
                 returncode=0, events=(), a0_by_invocation=None, drop_sidecar=False, drop_launcher_ws=False,
                 bad_parent_on=None):
        self.__dict__.update(locals())
        self.commands = []

    def __call__(self, command):
        self.commands.append(list(command))
        invocation = len(self.commands)
        args = child_b.parse_args(command[2:])
        a0_mib = (self.a0_by_invocation or {}).get(invocation, self.a0_mib)
        x = child_b.choose_x(a0_mib * MIB, select=args.select_x, fixed_x_mib=args.fixed_x,
                             x_target_mib=args.x_target_mib, x_min_mib=args.x_min_mib,
                             required_free_mib=args.required_free_mib)
        base_self, launcher = 30 * MIB, 5 * MIB
        t0 = 1000.0 * invocation
        records = [{"kind": "start", "pid": 2, "launcher_pid": 1,
                    "launcher_parent_pid": -1 if (self.wrong_parent or self.bad_parent_on == invocation)
                    else os.getpid(), "mode": "select_x" if args.select_x else "fixed_x", "sample_interval": 0.25}]
        timeline = [("baseline_hold", t0, t0 + args.baseline_hold, 0)]
        samples = []
        if x is None:
            records += self._hold("baseline_hold", t0, t0 + args.baseline_hold, base_self, launcher)
            records.append({"kind": "precondition", "a0_bytes": a0_mib * MIB, "x_mib": None,
                            "result": "PRECONDITION_FAILED"})
            records.append({"kind": "end", "status": "precondition_failed"})
            end = t0 + args.baseline_hold
        else:
            a_start = t0 + args.baseline_hold + 0.1
            r_start = a_start + args.alloc_hold + 0.1
            end = r_start + args.final_hold
            timeline += [("alloc_hold", a_start, a_start + args.alloc_hold, x * MIB),
                         ("final_hold", r_start, end, 0)]
            records += self._hold("baseline_hold", t0, t0 + args.baseline_hold, base_self, launcher)
            records.append({"kind": "precondition", "a0_bytes": a0_mib * MIB, "x_mib": x, "result": "OK"})
            records += self._hold("alloc_hold", a_start, a_start + args.alloc_hold, base_self + x * MIB, launcher)
            records += self._hold("final_hold", r_start, end, base_self, launcher)
            records.append({"kind": "end", "status": "ok"})
        t, index = t0 - 0.1, 0
        while t <= end + 0.1:
            extra = next((extra for _, lo, hi, extra in timeline if lo <= t <= hi), 0)
            samples.append({"index": index, "monotonic": t, "available_bytes": 2048 * MIB,
                            "harness_rss_bytes": int(base_self + launcher + extra * self.capture + self.offset)})
            index += 1
            t += self.gap
        sidecar = Path(command[command.index("--sidecar") + 1])
        if not self.drop_sidecar:
            if self.drop_launcher_ws:
                for record in records:
                    if record["kind"] == "ref":
                        record["launcher_ws"] = None
            sidecar.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return {"samples": samples, "events": list(self.events), "watchdog_abort": False,
                "returncode": self.returncode}

    @staticmethod
    def _hold(name, start, end, self_ws, launcher_ws):
        rows = [{"kind": "phase", "phase": name, "event": "start", "t": start}]
        t = start
        while t <= end:
            rows.append({"kind": "ref", "t": t, "self_ws": self_ws, "launcher_ws": launcher_ws})
            t += 0.25
        rows.append({"kind": "phase", "phase": name, "event": "end", "t": end})
        return rows


class FakeRunner:
    def __init__(self, *, m_factor=1.0, spread=None, fail=None, u_seconds=8.0, warmup_seconds=2.0):
        self.m_factor, self.spread, self.fail = m_factor, spread, fail or {}
        self.u_seconds, self.warmup_seconds = u_seconds, warmup_seconds
        self.calls: list[tuple[str, list[str], float]] = []
        self.pair_calls = 0

    def _index(self, arm):
        return sum(1 for kind, _, _ in self.calls if kind == arm)

    def unmonitored(self, command, timeout_s):
        self.calls.append(("U", list(command), timeout_s))
        if self._index("U") <= 3:
            status = self.fail.get(("W", self._index("U")), ma.OK)
            return {"status": status, "child_seconds": self.warmup_seconds, "child_seconds_rounded": 2.0,
                    "wrapper_seconds": 2.5}
        n = self._index("U") - 3
        status = self.fail.get(("U", n), ma.OK)
        return {"status": status, "child_seconds": self.u_seconds, "child_seconds_rounded": 8.0,
                "wrapper_seconds": 8.3}

    def monitored(self, command, max_seconds):
        self.calls.append(("M", list(command), max_seconds))
        n = self._index("M")
        status = self.fail.get(("M", n), ma.OK)
        seconds = self.u_seconds * self.m_factor
        if self.spread is not None:
            seconds = self.u_seconds * (1 + self.spread[n - 1])
        return {"status": status, "child_seconds": seconds, "child_seconds_rounded": round(seconds, 1),
                "wrapper_seconds": seconds + 0.2}
