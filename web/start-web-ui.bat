@echo off
chcp 65001 >nul
title Cordi v2 Web UI

set "ROOT=%~dp0.."
set "PORT=3081"

echo [1/4] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found in PATH
    pause
    exit /b 1
)

echo [2/4] Checking Node.js...
npm --version >nul 2>&1
if errorlevel 1 (
    echo Node.js not found in PATH
    pause
    exit /b 1
)

echo [3/4] Installing frontend dependencies...
pushd "%ROOT%\web\client"
call npm install --silent
popd

echo [4/4] Starting backend and frontend...
start "Cordi v2 Backend" cmd /k "cd /d "%ROOT%" && python -m web.server"
start "Cordi v2 Frontend" cmd /k "cd /d "%ROOT%\web\client" && npm run dev"

echo.
echo Waiting for frontend on port %PORT%...
:wait
timeout /t 2 >nul
powershell -Command "try { $r = Invoke-WebRequest -Uri http://127.0.0.1:%PORT% -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 goto wait

echo.
echo Opening browser...
start http://127.0.0.1:%PORT%

echo.
echo Cordi v2 Web UI is running.
echo Close the backend/frontend windows to stop.
pause
