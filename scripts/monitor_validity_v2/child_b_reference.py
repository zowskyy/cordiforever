"""MV-02B reference child (generic). Evidence policy is owned by mv02b_measurement, never by this child."""
import argparse, ctypes, gc, json, os, sys, time

MIB = 1024 * 1024


def choose_x(a0_bytes, *, select, fixed_x_mib, x_target_mib, x_min_mib, required_free_mib):
    """Frozen X rule (spec v2.1 section 5): returns X in MiB, or None for PRECONDITION failure."""
    required = required_free_mib * MIB
    if select:
        if a0_bytes >= x_target_mib * MIB + required:
            return x_target_mib
        if a0_bytes >= x_min_mib * MIB + required:
            return x_min_mib
        return None
    return fixed_x_mib if a0_bytes >= fixed_x_mib * MIB + required else None


def allocate_and_touch(x_mib):
    """Allocate X MiB and write one byte in every 4 KiB page so the allocation is in the working set."""
    block = bytearray(x_mib * MIB)
    for offset in range(0, len(block), 4096):
        block[offset] = 1
    return block


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar", required=True)
    parser.add_argument("--baseline-hold", type=float, required=True)
    parser.add_argument("--alloc-hold", type=float, required=True)
    parser.add_argument("--final-hold", type=float, required=True)
    parser.add_argument("--sample-interval", type=float, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--alloc-mib", type=int, help="allocate exactly this many MiB (no precondition)")
    mode.add_argument("--select-x", action="store_true", help="select X by the target/minimum rule")
    mode.add_argument("--fixed-x", type=int, help="allocate this X after re-checking the precondition")
    parser.add_argument("--x-target-mib", type=int)
    parser.add_argument("--x-min-mib", type=int)
    parser.add_argument("--required-free-mib", type=int, help="A0 must be >= X + this many MiB")
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    if sys.platform != "win32":
        print("B child requires Windows (GetProcessMemoryInfo / GlobalMemoryStatusEx)", file=sys.stderr)
        return 2
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]

    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                                           wintypes.DWORD]

    def working_set(handle):
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        return int(counters.WorkingSetSize)

    def avail_phys():
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.ullAvailPhys)

    def parent_of(target_pid):
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if snapshot in (None, wintypes.HANDLE(-1).value):
            return None
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            more = kernel32.Process32First(snapshot, ctypes.byref(entry))
            while more:
                if int(entry.th32ProcessID) == target_pid:
                    return int(entry.th32ParentProcessID)
                more = kernel32.Process32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return None

    out = open(args.sidecar, "w", encoding="utf-8", newline="\n")

    def emit(record):
        out.write(json.dumps(record, sort_keys=True) + "\n")
        out.flush()

    pid = os.getpid()
    launcher_pid = os.getppid()
    self_handle = kernel32.GetCurrentProcess()
    launcher_handle = kernel32.OpenProcess(0x1000, False, launcher_pid)  # PROCESS_QUERY_LIMITED_INFORMATION

    def reference():
        self_ws = working_set(self_handle)
        launcher_ws = working_set(launcher_handle) if launcher_handle else None
        emit({"kind": "ref", "t": time.monotonic(), "self_ws": self_ws, "launcher_ws": launcher_ws})

    def hold(name, seconds):
        emit({"kind": "phase", "phase": name, "event": "start", "t": time.monotonic()})
        end = time.monotonic() + seconds
        while True:
            reference()
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(args.sample_interval, remaining))
        emit({"kind": "phase", "phase": name, "event": "end", "t": time.monotonic()})

    emit({"kind": "start", "pid": pid, "launcher_pid": launcher_pid, "launcher_parent_pid": parent_of(launcher_pid),
          "mode": "alloc_mib" if args.alloc_mib is not None else ("select_x" if args.select_x else "fixed_x"),
          "sample_interval": args.sample_interval})
    hold("baseline_hold", args.baseline_hold)

    a0 = avail_phys()
    if args.alloc_mib is not None:
        x = args.alloc_mib
        emit({"kind": "precondition", "a0_bytes": a0, "x_mib": x, "result": "NOT_APPLICABLE"})
    else:
        if a0 is None:
            emit({"kind": "precondition", "a0_bytes": None, "x_mib": None, "result": "A0_UNREADABLE"})
            emit({"kind": "end", "status": "a0_unreadable"})
            out.close()
            return 0
        x = choose_x(a0, select=args.select_x, fixed_x_mib=args.fixed_x, x_target_mib=args.x_target_mib,
                     x_min_mib=args.x_min_mib, required_free_mib=args.required_free_mib)
        if x is None:
            emit({"kind": "precondition", "a0_bytes": a0, "x_mib": None, "result": "PRECONDITION_FAILED"})
            emit({"kind": "end", "status": "precondition_failed"})
            out.close()
            return 0
        emit({"kind": "precondition", "a0_bytes": a0, "x_mib": x, "result": "OK"})

    emit({"kind": "phase", "phase": "allocate", "event": "start", "t": time.monotonic()})
    block = allocate_and_touch(x)
    emit({"kind": "phase", "phase": "allocate", "event": "end", "t": time.monotonic()})
    hold("alloc_hold", args.alloc_hold)
    emit({"kind": "phase", "phase": "release", "event": "start", "t": time.monotonic()})
    del block
    gc.collect()
    emit({"kind": "phase", "phase": "release", "event": "end", "t": time.monotonic()})
    hold("final_hold", args.final_hold)
    emit({"kind": "end", "status": "ok"})
    out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
