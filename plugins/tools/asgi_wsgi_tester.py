"""ASGI/WSGI Tester plugin — starts Python web servers and tests endpoints."""

from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.plugin import Plugin


class ASGIWSGITester(Plugin):
    """Tests Python web apps by starting the server and sending HTTP requests.

    Supports:
    - WSGI (Flask, Django development server)
    - ASGI (FastAPI, Starlette, Django Channels)
    - Any server that can be started with a command

    This plugin is **deterministic and zero-token** — it does not call any LLM.
    It only starts a subprocess server and sends HTTP requests via the standard
    library `urllib` (no external HTTP client dependency required).

    Registered in both lite and full profiles.
    """

    name = "asgi_wsgi_tester"
    dependencies: tuple[str, ...] = ()

    __contract__ = {
        "version": "1.0",
        "provides": ("server_testing", "endpoint_verification"),
        "requires": (),
        "deterministic": True,
        "zero_token": True,
    }

    def __init__(self) -> None:
        super().__init__()
        self._server_process: Optional[subprocess.Popen] = None
        self._base_url = "http://127.0.0.1:8000"

    def start(self) -> None:
        """Initialize tester."""
        self._server_process = None

    def stop(self) -> None:
        """Clean up tester (kill server process)."""
        if self._server_process is not None:
            try:
                self._server_process.terminate()
                self._server_process.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    self._server_process.kill()
                except OSError:
                    pass
            finally:
                self._server_process = None

    def reset_run_state(self) -> None:
        """Reset per-run state at the beginning of each run()."""
        self.stop()

    def health_check(self) -> dict[str, Any]:
        """Verify the tester is functional."""
        return {
            "healthy": True,
            "plugin": self.name,
            "contract_version": self.__contract__.get("version", "1.0"),
            "capabilities": {
                "start_server": callable(getattr(self, "start_server", None)),
                "test_endpoint": callable(getattr(self, "test_endpoint", None)),
                "test_endpoints": callable(getattr(self, "test_endpoints", None)),
                "stop_server": callable(getattr(self, "stop_server", None)),
            },
        }

    def _find_available_port(self, start: int = 8000, end: int = 9000) -> int:
        """Find an available port to avoid conflicts."""
        for port in range(start, end):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
        return 8000  # Fallback

    def start_server(
        self,
        command: str,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 10.0,
        cwd: str | Path | None = None,
    ) -> bool:
        """Start a Python web server in a subprocess.

        Args:
            command: Command to start the server (e.g., "python server.py" or "uvicorn main:app").
            base_url: Base URL for the server.
            timeout: How long to wait for the server to start.
            cwd: Working directory for the server process.

        Returns:
            True if server started successfully, False otherwise.
        """
        self._base_url = base_url

        try:
            self._server_process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
            )

            # Wait for server to start
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    self._check_server_started()
                    if self._server_process.poll() is not None:
                        # Process exited early
                        stderr_output = self._server_process.stderr.read().decode("utf-8", errors="replace") if self._server_process.stderr else ""
                        return False
                    return True
                except Exception:
                    time.sleep(0.5)

            # Timeout — kill the process
            self.stop()
            return False

        except Exception:
            return False

    def _check_server_started(self) -> None:
        """Check if the server is responding by making a simple HTTP request."""
        import urllib.request
        import urllib.error

        try:
            urllib.request.urlopen(self._base_url, timeout=1.0)
        except urllib.error.HTTPError:
            # HTTP error means server is running (just returned an error code)
            pass
        except urllib.error.URLError:
            # Connection refused — server not ready yet
            raise

    def test_endpoint(
        self,
        method: str,
        path: str,
        expected_status: int = 200,
        json_body: Optional[Dict[str, Any]] = None,
        expected_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Test a single endpoint.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            path: URL path (e.g., "/api/items").
            expected_status: Expected HTTP status code.
            json_body: Optional JSON body for POST/PUT requests.
            expected_keys: Optional list of keys that should be in the response JSON.

        Returns:
            Dict with "passed", "status_code", "response", "error".
        """
        import urllib.request
        import urllib.error
        import json as json_module

        url = f"{self._base_url}{path}"
        method_upper = method.upper()

        headers: Dict[str, str] = {}
        data: bytes | None = None

        if json_body is not None:
            data = json_module.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method_upper)

        try:
            with urllib.request.urlopen(req, timeout=5.0) as response:
                status_code = response.getcode()
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            status_code = e.code
            body = e.read().decode("utf-8", errors="replace")
        except Exception as e:
            return {
                "passed": False,
                "status_code": None,
                "response": None,
                "error": str(e),
            }

        passed = (status_code == expected_status)

        if expected_keys and passed:
            try:
                response_data = json_module.loads(body)
                if isinstance(response_data, dict):
                    passed = all(key in response_data for key in expected_keys)
                elif isinstance(response_data, list) and "items" in str(expected_keys).lower():
                    # List response — check if any item has expected keys
                    if response_data:
                        passed = all(
                            all(k in item for k in expected_keys)
                            for item in response_data
                            if isinstance(item, dict)
                        )
            except (ValueError, json_module.JSONDecodeError):
                passed = False

        return {
            "passed": passed,
            "status_code": status_code,
            "response": body[:500],
            "error": None if passed else f"Expected status {expected_status}, got {status_code}",
        }

    def test_endpoints(
        self,
        endpoints: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Test multiple endpoints (e.g., full CRUD).

        Args:
            endpoints: List of endpoint configs with method, path, expected_status, etc.

        Returns:
            Dict with "passed", "results" (list of individual results), "summary".
        """
        results = []
        all_passed = True

        for endpoint in endpoints:
            result = self.test_endpoint(
                endpoint.get("method", "GET"),
                endpoint.get("path", "/"),
                endpoint.get("expected_status", 200),
                endpoint.get("json_body"),
                endpoint.get("expected_keys"),
            )
            results.append({
                "method": endpoint.get("method", "GET"),
                "path": endpoint.get("path", "/"),
                **result,
            })
            if not result["passed"]:
                all_passed = False

        passed_count = sum(1 for r in results if r["passed"])
        return {
            "passed": all_passed,
            "results": results,
            "summary": f"{passed_count}/{len(results)} endpoints passed",
        }

    def stop_server(self) -> None:
        """Stop the server process."""
        self.stop()
