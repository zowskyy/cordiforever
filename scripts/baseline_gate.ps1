# baseline_gate.ps1 - Cordi v2 baseline validation gate
# Re-runs deterministic + live integration suites and asserts stable counts.
# Usage: powershell -File scripts/baseline_gate.ps1
param(
    [switch]$SkipLive
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "project venv not found: $python" }
# C:\tmp breaks tempfile.mkdtemp under the sandbox (hostile ACLs); a TEMP basetemp runs the same suite.
$basetemp = Join-Path $env:TEMP "pytest_cordii_gate"
$logPath = Join-Path $PSScriptRoot "..\logs\baseline_gate.log"

# Thresholds (update when the baseline contract changes). Raised 2026-09-14 from the 2026-08-30 value 288 (785, 795 after the diagnose_v1 build, 801 after the duplicate-notice repair, 809 after the gemma_progress_v1 build, 817 after the qwen_evidence_v1 build, 827 after the qwen_extract_v1 build, 846 after the qwen_localedit_v1 build, 851 after the qwen_selectorkind_v1 build, 864 after the research-state validator, 875 after the heldout scorer + validator extensions).
$MIN_PASSED = 875
$MAX_SKIPPED = 8
$MIN_LIVE_PASSED = 4
# Known environmental failures: bare `python` resolves to the Windows Store stub. Any failure NOT listed fails the gate.
$KNOWN_ENV_FAILURES = @(
    "tests/test_run_command.py::test_run_command_timeout",
    "tests/test_run_command.py::test_run_command_workspace_cwd"
)


function Ensure-LogDir {
    $logDir = Split-Path -Parent $logPath
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
}


function Write-Log([string]$line) {
    Ensure-LogDir
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts | $line" | Out-File -Append -FilePath $logPath
}


function Invoke-Pytest([string[]]$ExtraArgs) {
    $argsList = @("-m", "pytest", "-p", "no:cacheprovider", "--basetemp", $basetemp, "--tb=no", "-rf") + $ExtraArgs + @("-q")
    Write-Host ">>> $python $($argsList -join ' ')"
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'  # pytest writes warnings to stderr; judge by the parsed result, not the stream
    Push-Location $root
    try { $output = & $python @argsList 2>&1 | Out-String } finally { Pop-Location; $ErrorActionPreference = $previous }
    Write-Host $output
    $failed = @([regex]::Matches($output, "(?m)^FAILED (\S+)") | ForEach-Object { $_.Groups[1].Value })
    $unexpected = @($failed | Where-Object { $KNOWN_ENV_FAILURES -notcontains $_ })
    if ($unexpected.Count -gt 0) {
        throw "pytest reported unexpected failures:`n$($unexpected -join "`n")"
    }
    if ($LASTEXITCODE -ne 0 -and $failed.Count -eq 0) {
        throw "pytest failed with exit code $LASTEXITCODE and no parsable FAILED lines (collection/usage error?)"
    }
    return $output
}


# Calibration validation (runs before tests)
Write-Host "`n==> Calibration validation"
# capacity_calculator.py has no "1b" (gemma) option; the 1.5b preset check is what it supports.
$calibOutput = & $python (Join-Path $root "scripts\capacity_calculator.py") --model 1.5b 2>&1 | Out-String
Write-Host $calibOutput
if ($LASTEXITCODE -ne 0) {
    $msg = "CALIBRATION FAIL: capacity_calculator.py --model 1.5b failed"
    Write-Host $msg -ForegroundColor Red
    Write-Log "calibration=FAIL"
    throw $msg
}
Write-Log "calibration=OK"


Write-Host "`n==> Research-state validation"
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$researchOutput = & $python (Join-Path $root "scripts\validate_research_state.py") $root 2>&1 | Out-String
$researchExit = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
Write-Host $researchOutput
if ($researchExit -ne 0) {
    $msg = "RESEARCH STATE FAIL: scripts/validate_research_state.py reported errors"
    Write-Host $msg -ForegroundColor Red
    Write-Log "research_state=FAIL"
    throw $msg
}
Write-Log "research_state=OK"


Write-Host "`n==> Deterministic gate"
$det = Invoke-Pytest @()
# Robust parsing: look for "X passed" and "Y skipped" anywhere in output
if (-not ($det -match "(\d+) passed")) {
    throw "Could not parse 'passed' count from deterministic output`n$det"
}
$passed = [long]$Matches[1]

if (-not ($det -match "(\d+) skipped")) {
    throw "Could not parse 'skipped' count from deterministic output`n$det"
}
$skipped = [long]$Matches[1]

Write-Host "Passed: $passed, Skipped: $skipped"
if ($passed -lt $MIN_PASSED) {
    $msg = "BASELINE FAIL: $passed passed (expected >=$MIN_PASSED)"
    Write-Host $msg -ForegroundColor Red
    Write-Log "deterministic=FAIL passed=$passed skipped=$skipped"
    throw $msg
}
if ($skipped -gt $MAX_SKIPPED) {
    $msg = "BASELINE FAIL: $skipped skipped (expected <=$MAX_SKIPPED)"
    Write-Host $msg -ForegroundColor Red
    Write-Log "deterministic=FAIL passed=$passed skipped=$skipped"
    throw $msg
}
Write-Log "deterministic=OK passed=$passed skipped=$skipped"


$livePassed = $null
$liveSkipped = $null
if (-not $SkipLive) {
    Write-Host "`n==> Live integration gate"
    $live = Invoke-Pytest @("--live", "-k", "integration")
    if (-not ($live -match "(\d+) passed")) {
        throw "Could not parse 'passed' count from live output`n$live"
    }
    $livePassed = [long]$Matches[1]

    if (-not ($live -match "(\d+) skipped")) {
        throw "Could not parse 'skipped' count from live output`n$live"
    }
    $liveSkipped = [long]$Matches[1]

    Write-Host "Live passed: $livePassed, skipped: $liveSkipped"
    if ($livePassed -lt $MIN_LIVE_PASSED) {
        $msg = "LIVE FAIL: $livePassed/$MIN_LIVE_PASSED integration tests passed (expected >=$MIN_LIVE_PASSED)"
        Write-Host $msg -ForegroundColor Red
        Write-Log "live=FAIL passed=$livePassed skipped=$liveSkipped"
        throw $msg
    }
    Write-Log "live=OK passed=$livePassed skipped=$liveSkipped"
} else {
    Write-Host "`n==> Skipping live gate (--SkipLive)"
    Write-Log "deterministic=OK passed=$passed skipped=$skipped live=SKIPPED"
}


$summary = "baseline=OK passed=$passed skipped=$skipped live=$(if ($null -ne $livePassed) { $livePassed } else { 'SKIPPED' })"
Write-Host "`n==> $summary" -ForegroundColor Green
Write-Log $summary
