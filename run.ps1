$ErrorActionPreference = "Stop"

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "Ollama is not installed or is not on PATH."
}

& ollama list | Out-Host

& ".\.venv\Scripts\python.exe" .\main.py --workspace .\workspace --model gemma3:1b
