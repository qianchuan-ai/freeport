@echo off
setlocal
set "DIR=%~dp0"

:: Use py launcher (avoids hardcoding a broken python path)
where py >nul 2>nul
if %errorlevel% neq 0 (
  echo [FreePort] py launcher not found. Install Python and ensure 'py' is on PATH.
  pause
  exit /b 1
)

echo [FreePort] Starting proxy on http://127.0.0.1:41980 ... (keep this window open)
py "%DIR%freeport_proxy.py"
endlocal
