"""Standalone launcher for the Continuity Kernel Web Dashboard.

Runs the WebDashboard FastAPI app directly without the full plugin registry,
so the dashboard can be started independently for quick access.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root is importable
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> int:
    # Ensure required dependencies are available
    missing = []
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        missing.append("uvicorn")
    try:
        import sse_starlette  # noqa: F401
    except ImportError:
        missing.append("sse-starlette")

    if missing:
        print(f"[INFO] Installing missing dependencies: {', '.join(missing)}")
        import subprocess
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            print("[OK] Dependencies installed.")
        except Exception as exc:
            print(f"[ERROR] Failed to install dependencies: {exc}")
            return 1

    import uvicorn
    from plugins.web.server import WebDashboard

    host = "127.0.0.1"
    port = 3080
    print(f"[INFO] Starting Continuity Kernel Dashboard at http://{host}:{port}")
    print("[INFO] Press Ctrl+C to stop.")

    try:
        plugin = WebDashboard()
        plugin.context = type("Ctx", (), {"plugins": {}, "config": {}, "events": type("Bus", (), {"emit": lambda *a, **k: None})()})()
        plugin.start()
        # Give the server thread a moment to bind
        import time
        time.sleep(1)
        # Keep main thread alive
        while True:
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                break
        plugin.stop()
    except KeyboardInterrupt:
        print("\n[INFO] Dashboard stopped.")
    except Exception as exc:
        print(f"[ERROR] Failed to start dashboard: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
