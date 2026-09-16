"""External resource monitor for CORDI benchmark runs (S2 GAP-2, v1).

Launches a benchmark command as a subprocess and samples system and process memory from OUTSIDE
that process, so the evaluator is never modified and no sampling thread runs inside the measured
process.

Design constraints this file honours:

* Ollama discovery is anchored to the process OWNING the listener on 127.0.0.1:11434, plus its
  descendant inference processes. The tray GUI is never counted merely because of its name; it is
  included only if it is itself the port owner or a descendant of it. Ambiguous ownership fails
  closed.
* Every quantity is labelled direct or derived. Process RSS is never called "model memory".
* Every extremum obtained by sampling is named a SAMPLED value. The monitor never claims a
  continuous-time minimum or maximum.
* Where the platform exposes no reliable signal, the field is UNKNOWN. No substitute is invented.
* No third-party dependency: the Windows backend uses ctypes against the Win32 API and the POSIX
  backend reads /proc, so CI can exercise the same decision logic.

The decision logic (`summarize`, `watchdog_abort_index`, `evaluate_gate`) is pure and separated from
the sampling thread so it can be property- and mutation-tested deterministically.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

ROOT = Path(__file__).resolve().parents[1]

MIB = 1024 * 1024

#: [POLICY] preregistered safety-margin policy for EXP-SUBQ-01's first registered resource protocol.
#: It is NOT empirically established, NOT guaranteed safe, and NOT measured transient coverage.
RESERVE_MIB = 512

#: [POLICY] fixed sampling interval. Every extremum derived from it is a SAMPLED value.
SAMPLE_INTERVAL_SECONDS = 0.25

#: [POLICY] WD-01. Consecutive samples below RESERVE that terminate the run (~2 s at 250 ms).
WATCHDOG_CONSECUTIVE_SAMPLES = 8

#: [POLICY] reporting threshold for enumerating large non-system user processes in preflight.
LARGE_PROCESS_REPORT_MIB = 100

OLLAMA_PORT = 11434

PHASES = ("baseline", "harness_start", "model_load", "generation", "unload", "final")

#: Classes of discretionary user workload that must not coexist with a measured run. Matched as a
#: class, by substring of the process name, so ordinary Windows service churn is never failed on.
EXCLUDED_WORKLOAD_CLASSES: dict[str, tuple[str, ...]] = {
    "claude_code": ("claude",),
    "grok_bot": ("grok",),
    "browser": ("chrome", "msedge", "firefox", "brave", "opera"),
    "dev_tool": ("code", "devenv", "pycharm", "idea", "sublime_text"),
    "other_model_runtime": ("lmstudio", "llama-server", "llama_cpp", "koboldcpp", "vllm", "text-generation"),
    "other_benchmark": ("pytest", "repo_task_eval"),
}

UNKNOWN = "UNKNOWN"


class MonitorError(RuntimeError):
    """A condition under which the monitor refuses to produce a measurement."""


# ============================================================================= probes

@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    ppid: int
    rss_bytes: int
    page_faults: int | None


class SystemProbe(Protocol):
    """Platform access. Implementations return DIRECT measurements only."""

    def total_memory_bytes(self) -> int: ...
    def available_memory_bytes(self) -> int: ...
    def committed_bytes(self) -> int | None: ...
    def processes(self) -> list[ProcessInfo]: ...
    def listener_pids(self, port: int) -> list[int]: ...


class WindowsProbe:
    """Win32 backend via ctypes. No third-party dependency."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        self._MEMORYSTATUSEX = MEMORYSTATUSEX

    def _status(self):
        status = self._MEMORYSTATUSEX()
        status.dwLength = self._ctypes.sizeof(self._MEMORYSTATUSEX)
        if not self._kernel32.GlobalMemoryStatusEx(self._ctypes.byref(status)):
            raise MonitorError("GlobalMemoryStatusEx failed")
        return status

    def total_memory_bytes(self) -> int:
        return int(self._status().ullTotalPhys)

    def available_memory_bytes(self) -> int:
        return int(self._status().ullAvailPhys)

    def committed_bytes(self) -> int | None:
        status = self._status()
        return int(status.ullTotalPageFile - status.ullAvailPageFile)

    def processes(self) -> list[ProcessInfo]:
        ctypes, wintypes = self._ctypes, self._wintypes

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        snapshot = self._kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if snapshot in (-1, 0xFFFFFFFF):
            raise MonitorError("CreateToolhelp32Snapshot failed")
        out: list[ProcessInfo] = []
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            more = self._kernel32.Process32First(snapshot, ctypes.byref(entry))
            while more:
                pid = int(entry.th32ProcessID)
                name = entry.szExeFile.decode("utf-8", "replace")
                rss, faults = 0, None
                handle = self._kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                if handle:
                    try:
                        counters = PROCESS_MEMORY_COUNTERS()
                        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                        if self._psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                            rss = int(counters.WorkingSetSize)
                            faults = int(counters.PageFaultCount)
                    finally:
                        self._kernel32.CloseHandle(handle)
                out.append(ProcessInfo(pid=pid, name=name, ppid=int(entry.th32ParentProcessID),
                                       rss_bytes=rss, page_faults=faults))
                more = self._kernel32.Process32Next(snapshot, ctypes.byref(entry))
        finally:
            self._kernel32.CloseHandle(snapshot)
        return out

    def listener_pids(self, port: int) -> list[int]:
        """Parse `netstat -ano` once per discovery, never per sample."""
        try:
            proc = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            raise MonitorError(f"could not enumerate TCP listeners: {exc}") from exc
        pids: list[int] = []
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[3].upper() != "LISTENING":
                continue
            local = parts[1]
            if local.rsplit(":", 1)[-1] != str(port):
                continue
            try:
                pids.append(int(parts[4]))
            except ValueError:
                continue
        return sorted(set(pids))


class LinuxProbe:
    """POSIX backend reading /proc. Exists so CI exercises the same decision logic."""

    def _meminfo(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            value = rest.strip().split()
            if value and value[0].isdigit():
                out[key] = int(value[0]) * 1024
        return out

    def total_memory_bytes(self) -> int:
        return self._meminfo()["MemTotal"]

    def available_memory_bytes(self) -> int:
        info = self._meminfo()
        return info.get("MemAvailable", info.get("MemFree", 0))

    def committed_bytes(self) -> int | None:
        return self._meminfo().get("Committed_AS")

    def processes(self) -> list[ProcessInfo]:
        out: list[ProcessInfo] = []
        page = os.sysconf("SC_PAGE_SIZE")
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            try:
                statm = (entry / "statm").read_text().split()
                rss = int(statm[1]) * page
                stat = (entry / "stat").read_text()
                name = stat[stat.index("(") + 1:stat.rindex(")")]
                after = stat[stat.rindex(")") + 2:].split()
                ppid = int(after[1])
                faults = int(after[6]) + int(after[8])  # minflt + majflt
            except (OSError, ValueError, IndexError):
                continue
            out.append(ProcessInfo(pid=pid, name=name, ppid=ppid, rss_bytes=rss, page_faults=faults))
        return out

    def listener_pids(self, port: int) -> list[int]:
        try:
            proc = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            raise MonitorError(f"could not enumerate TCP listeners: {exc}") from exc
        pids: list[int] = []
        for line in proc.stdout.splitlines():
            if f":{port} " not in line and not line.rstrip().endswith(f":{port}"):
                continue
            marker = "pid="
            index = line.find(marker)
            while index != -1:
                digits = ""
                for char in line[index + len(marker):]:
                    if char.isdigit():
                        digits += char
                    else:
                        break
                if digits:
                    pids.append(int(digits))
                index = line.find(marker, index + 1)
        return sorted(set(pids))


def default_probe() -> SystemProbe:
    return WindowsProbe() if sys.platform == "win32" else LinuxProbe()


# ============================================================================= discovery (pure)

def descendants(processes: Sequence[ProcessInfo], root_pid: int) -> set[int]:
    """Transitive descendants of root_pid, plus root_pid itself."""
    by_parent: dict[int, list[int]] = {}
    for info in processes:
        by_parent.setdefault(info.ppid, []).append(info.pid)
    seen = {root_pid}
    stack = [root_pid]
    while stack:
        current = stack.pop()
        for child in by_parent.get(current, ()):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def discover_ollama_pids(probe: SystemProbe, port: int = OLLAMA_PORT) -> tuple[int, set[int]]:
    """Anchor on the listener owner, then include its descendants. Fails closed on ambiguity.

    The tray GUI is NOT included by name; it appears only if it is the owner or a descendant.
    """
    owners = probe.listener_pids(port)
    if not owners:
        raise MonitorError(f"no process is listening on port {port}; Ollama ownership cannot be established")
    if len(owners) > 1:
        raise MonitorError(f"multiple processes listen on port {port} ({owners}); ownership is ambiguous")
    owner = owners[0]
    return owner, descendants(probe.processes(), owner)


# ============================================================================= sampling

@dataclass(frozen=True)
class Sample:
    index: int
    monotonic: float
    phase: str
    available_bytes: int
    committed_bytes: int | None
    ollama_rss_bytes: int
    harness_rss_bytes: int
    monitor_rss_bytes: int
    ollama_page_faults: int | None


def take_sample(probe: SystemProbe, index: int, phase: str, ollama_pids: set[int],
                harness_pids: set[int], monitor_pid: int) -> Sample:
    processes = probe.processes()
    by_pid = {info.pid: info for info in processes}
    def rss(pids: Iterable[int]) -> int:
        return sum(by_pid[pid].rss_bytes for pid in pids if pid in by_pid)
    faults = [by_pid[pid].page_faults for pid in ollama_pids if pid in by_pid]
    return Sample(
        index=index,
        monotonic=time.monotonic(),
        phase=phase,
        available_bytes=probe.available_memory_bytes(),
        committed_bytes=probe.committed_bytes(),
        ollama_rss_bytes=rss(ollama_pids),
        harness_rss_bytes=rss(harness_pids),
        monitor_rss_bytes=rss([monitor_pid]),
        ollama_page_faults=None if any(f is None for f in faults) or not faults else sum(faults),
    )


# ============================================================================= decisions (pure)

def watchdog_abort_index(samples: Sequence[Sample], reserve_bytes: int,
                         consecutive: int = WATCHDOG_CONSECUTIVE_SAMPLES) -> int | None:
    """WD-01. Index of the sample completing `consecutive` consecutive sub-reserve samples."""
    run = 0
    for sample in samples:
        run = run + 1 if sample.available_bytes < reserve_bytes else 0
        if run >= consecutive:
            return sample.index
    return None


def summarize(samples: Sequence[Sample]) -> dict[str, Any]:
    """Every extremum here is a SAMPLED value, never a continuous-time extremum."""
    if not samples:
        return {"samples": 0, "sampled_available_min_bytes": UNKNOWN, "sampled_drop_max_bytes": UNKNOWN}
    available = [s.available_bytes for s in samples]
    drops = [available[i] - available[i + 1] for i in range(len(available) - 1)]
    per_phase: dict[str, dict[str, int]] = {}
    for phase in PHASES:
        phase_samples = [s for s in samples if s.phase == phase]
        if phase_samples:
            per_phase[phase] = {
                "sampled_available_min_bytes": min(s.available_bytes for s in phase_samples),
                "sampled_ollama_rss_peak_bytes": max(s.ollama_rss_bytes for s in phase_samples),
                "sampled_harness_rss_peak_bytes": max(s.harness_rss_bytes for s in phase_samples),
                "samples": len(phase_samples),
            }
    faults = [s.ollama_page_faults for s in samples if s.ollama_page_faults is not None]
    committed = [s.committed_bytes for s in samples if s.committed_bytes is not None]
    return {
        "samples": len(samples),
        "sampled_available_min_bytes": min(available),
        "sampled_available_max_bytes": max(available),
        "sampled_drop_max_bytes": max(drops) if drops else 0,
        "sampled_ollama_rss_peak_bytes": max(s.ollama_rss_bytes for s in samples),
        "sampled_harness_rss_peak_bytes": max(s.harness_rss_bytes for s in samples),
        "sampled_monitor_rss_peak_bytes": max(s.monitor_rss_bytes for s in samples),
        "sampled_committed_max_bytes": max(committed) if committed else UNKNOWN,
        "ollama_page_fault_delta": (max(faults) - min(faults)) if len(faults) >= 2 else UNKNOWN,
        "per_phase": per_phase,
    }


def evaluate_gate(summary: Mapping[str, Any], *, reserve_bytes: int, oom_or_death: bool,
                  watchdog_abort: bool, load_succeeded: bool) -> dict[str, Any]:
    """The runtime resource gate. The reserve appears exactly once, on one side of one inequality."""
    sampled_min = summary.get("sampled_available_min_bytes")
    conditions = {
        "sampled_available_min_at_or_above_reserve":
            isinstance(sampled_min, int) and sampled_min >= reserve_bytes,
        "zero_oom_or_process_death": not oom_or_death,
        "no_watchdog_abort": not watchdog_abort,
        "model_load_succeeded": load_succeeded,
    }
    return {"passed": all(conditions.values()), "conditions": conditions,
            "reserve_bytes": reserve_bytes,
            "reserve_basis": "[POLICY] preregistered safety-margin policy; not empirically established, "
                             "not guaranteed safe, not measured transient coverage"}


# ============================================================================= preflight (pure core)

def classify_workload(name: str) -> str | None:
    lowered = name.lower()
    for workload_class, needles in EXCLUDED_WORKLOAD_CLASSES.items():
        if any(needle in lowered for needle in needles):
            return workload_class
    return None


def preflight_snapshot(probe: SystemProbe, *, port: int = OLLAMA_PORT,
                       loaded_models: Sequence[str] | None = None) -> dict[str, Any]:
    """Detects and reports. It never terminates anything."""
    processes = probe.processes()
    threshold = LARGE_PROCESS_REPORT_MIB * MIB
    large = sorted(({"pid": p.pid, "name": p.name, "rss_bytes": p.rss_bytes}
                    for p in processes if p.rss_bytes >= threshold),
                   key=lambda row: -row["rss_bytes"])
    violations = sorted({cls for p in processes if (cls := classify_workload(p.name)) is not None
                         and p.rss_bytes >= threshold})
    try:
        owners = probe.listener_pids(port)
    except MonitorError:
        owners = []
    return {
        "total_memory_bytes": probe.total_memory_bytes(),
        "available_bytes": probe.available_memory_bytes(),
        "committed_bytes": probe.committed_bytes() if probe.committed_bytes() is not None else UNKNOWN,
        "process_snapshot": [{"pid": p.pid, "name": p.name, "rss_bytes": p.rss_bytes} for p in processes],
        "large_user_processes": large,
        "excluded_workload_classes_present": violations,
        "ollama_listener_pids": owners,
        "ollama_loaded_models": list(loaded_models) if loaded_models is not None else UNKNOWN,
        "quiesced": not violations,
    }


def check_symmetry(incumbent: Mapping[str, Any], challenger: Mapping[str, Any],
                   tolerance_bytes: int = 256 * MIB) -> dict[str, Any]:
    """[POLICY] 256 MiB starting-state tolerance, applied identically to both runs."""
    delta = abs(int(incumbent["available_bytes"]) - int(challenger["available_bytes"]))
    reasons = []
    if delta > tolerance_bytes:
        reasons.append(f"AVAIL_0 differs by {delta} bytes, above the {tolerance_bytes}-byte tolerance")
    for label, snapshot in (("incumbent", incumbent), ("challenger", challenger)):
        if snapshot.get("excluded_workload_classes_present"):
            reasons.append(f"{label} preflight carried excluded workloads "
                           f"{snapshot['excluded_workload_classes_present']}")
    return {"comparable": not reasons, "avail0_delta_bytes": delta,
            "tolerance_bytes": tolerance_bytes, "reasons": reasons}


# ============================================================================= run

DIRECT_VS_DERIVED: dict[str, str] = {
    "total_memory_bytes": "direct",
    "available_bytes": "direct",
    "committed_bytes": "direct",
    "ollama_rss_bytes": "direct",
    "harness_rss_bytes": "direct",
    "monitor_rss_bytes": "direct",
    "ollama_page_faults": "direct",
    "sampled_available_min_bytes": "direct (sampled extremum, not a continuous-time minimum)",
    "sampled_available_max_bytes": "direct (sampled extremum, not a continuous-time maximum)",
    "sampled_drop_max_bytes": "derived (largest fall between consecutive samples; bounds no unobserved transient)",
    "sampled_ollama_rss_peak_bytes": "direct (sampled extremum)",
    "sampled_harness_rss_peak_bytes": "direct (sampled extremum)",
    "sampled_monitor_rss_peak_bytes": "direct (sampled extremum)",
    "sampled_committed_max_bytes": "direct (sampled extremum)",
    "ollama_page_fault_delta": "derived proxy (thrash proxy, not a thrash measurement)",
    "model_attributable_delta_bytes": "derived, descriptive only; NOT model memory and NOT a gate input",
    "footprint_bytes": "derived, descriptive only (AVAIL_0 minus sampled AVAIL_MIN)",
}


@dataclass
class MonitoredRun:
    samples: list[Sample] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    phase: str = "baseline"
    watchdog_abort: bool = False
    returncode: int | None = None


def run_monitored(command: Sequence[str], *, probe: SystemProbe | None = None,
                  reserve_bytes: int = RESERVE_MIB * MIB,
                  interval: float = SAMPLE_INTERVAL_SECONDS,
                  discover_ollama: bool = True, cwd: Path | None = None,
                  max_seconds: float | None = None) -> tuple[MonitoredRun, dict[str, Any]]:
    """Launch `command` and sample around it. Returns the run and its artifact payload."""
    probe = probe or default_probe()
    ollama_owner: int | None = None
    ollama_pids: set[int] = set()
    if discover_ollama:
        ollama_owner, ollama_pids = discover_ollama_pids(probe)

    baseline = preflight_snapshot(probe)
    state = MonitoredRun()
    monitor_pid = os.getpid()

    proc = subprocess.Popen(list(command), cwd=str(cwd or ROOT),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    state.phase = "harness_start"
    stop = threading.Event()
    started = time.monotonic()

    def loop() -> None:
        index = 0
        while not stop.is_set():
            harness_pids = descendants(probe.processes(), proc.pid)
            sample = take_sample(probe, index, state.phase, ollama_pids, harness_pids, monitor_pid)
            state.samples.append(sample)
            if watchdog_abort_index(state.samples[-WATCHDOG_CONSECUTIVE_SAMPLES:], reserve_bytes) is not None \
                    and len(state.samples) >= WATCHDOG_CONSECUTIVE_SAMPLES:
                state.watchdog_abort = True
                state.events.append({"event": "watchdog_abort", "sample_index": index,
                                     "reserve_bytes": reserve_bytes})
                proc.terminate()
                return
            index += 1
            stop.wait(interval)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        proc.communicate(timeout=max_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        state.events.append({"event": "timeout", "seconds": max_seconds})
        proc.communicate()
    finally:
        stop.set()
        thread.join(timeout=5)
    state.returncode = proc.returncode
    state.phase = "final"

    if state.returncode not in (0, None) and not state.watchdog_abort:
        state.events.append({"event": "nonzero_exit", "returncode": state.returncode})

    summary = summarize(state.samples)
    avail0 = baseline["available_bytes"]
    sampled_min = summary.get("sampled_available_min_bytes")
    footprint = (avail0 - sampled_min) if isinstance(sampled_min, int) else UNKNOWN
    artifact = {
        "schema": "resource_v1",
        "policy": {
            "reserve_mib": RESERVE_MIB,
            "reserve_basis": "[POLICY]",
            "sample_interval_seconds": interval,
            "watchdog_consecutive_samples": WATCHDOG_CONSECUTIVE_SAMPLES,
            "large_process_report_mib": LARGE_PROCESS_REPORT_MIB,
        },
        "command": list(command),
        "platform": sys.platform,
        "preflight": baseline,
        "ollama_owner_pid": ollama_owner,
        "ollama_pids": sorted(ollama_pids),
        "summary": summary,
        "footprint_bytes": footprint,
        "events": state.events,
        "returncode": state.returncode,
        "watchdog_abort": state.watchdog_abort,
        "duration_seconds": round(time.monotonic() - started, 3),
        "direct_vs_derived": DIRECT_VS_DERIVED,
    }
    artifact["gate"] = evaluate_gate(
        summary, reserve_bytes=reserve_bytes,
        oom_or_death=any(e["event"] in ("timeout", "nonzero_exit") for e in state.events),
        watchdog_abort=state.watchdog_abort,
        load_succeeded=state.returncode == 0 or state.returncode is None,
    )
    return state, artifact


# ============================================================================= cli

def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="External resource monitor (S2 GAP-2 v1)")
    sub = parser.add_subparsers(dest="mode", required=True)
    pre = sub.add_parser("preflight", help="report machine state; never terminates anything")
    pre.add_argument("--out", type=Path, default=None)
    run = sub.add_parser("run", help="launch a command under sampling")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--no-ollama", action="store_true", help="do not require an Ollama listener")
    run.add_argument("--max-seconds", type=float, default=None)
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    probe = default_probe()
    if args.mode == "preflight":
        snapshot = preflight_snapshot(probe)
        text = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
        if args.out:
            args.out.write_text(text, encoding="utf-8", newline="\n")
        print(json.dumps({"quiesced": snapshot["quiesced"],
                          "excluded_workload_classes_present": snapshot["excluded_workload_classes_present"],
                          "available_bytes": snapshot["available_bytes"]}))
        return 0 if snapshot["quiesced"] else 2

    command = [c for c in args.command if c != "--"]
    if not command:
        parser.error("run requires a command")
    _state, artifact = run_monitored(command, probe=probe, discover_ollama=not args.no_ollama,
                                     max_seconds=args.max_seconds)
    args.out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"gate_passed": artifact["gate"]["passed"], "returncode": artifact["returncode"],
                      "watchdog_abort": artifact["watchdog_abort"], "samples": artifact["summary"]["samples"]}))
    return 0 if artifact["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
