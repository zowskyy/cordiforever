# Qwen Code launcher for Cordi v2
# Usage: .\run-qwen.ps1 "your prompt here"
# Requires OPENAI_API_KEY in your environment (setx OPENAI_API_KEY <key>).
# NEVER hardcode keys in this repo — they end up in git history.
if (-not $env:OPENAI_API_KEY) {
    throw "OPENAI_API_KEY is not set. Export it in your environment first (e.g. setx OPENAI_API_KEY <key>), then reopen the shell."
}
$env:OPENAI_BASE_URL = "https://ws-e5p0odlm64sslhug.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
$env:OPENAI_MODEL = "qwen3-coder-480b-a35b-instruct"

$prompt = $args -join " "

if ($prompt) {
    acpx --approve-all qwen exec $prompt
} else {
    Write-Host "Usage: .\run-qwen.ps1 'your coding task here'"
    Write-Host "Example: .\run-qwen.ps1 'fix the failing tests'"
}
