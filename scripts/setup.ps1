$ErrorActionPreference = "Stop"

Write-Host "=== Cordis-Lite Phase 0-1 Windows Setup ==="

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' was not found. Install Python 3.11+ from python.org and enable the Python launcher."
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "Ollama was not found. Install Ollama for Windows, restart PowerShell, then run this script again."
}

$pythonVersion = & py -3 --version
Write-Host "Python: $pythonVersion"

if (-not (Test-Path ".venv")) {
    & py -3 -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install "pytest>=8,<9"

Write-Host ""
Write-Host "Pulling gemma3:1b..."
& ollama pull gemma3:1b

Write-Host ""
Write-Host "Installed Ollama models:"
& ollama list

Write-Host ""
Write-Host "Running Phase 0-1 tests..."
& ".\.venv\Scripts\python.exe" -m pytest -q

Write-Host ""
Write-Host "Setup complete."
Write-Host "Start the agent with:"
Write-Host "  .\run.ps1"
