@echo off
title IvyeaOps
rem Force Python UTF-8 mode so reading UTF-8/中文 config & log files never hits a
rem GBK decode error on 中文 Windows (default code page cp936).
set PYTHONUTF8=1
cd /d "%~dp0server"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Not installed yet. Run the installer first ^(double-click the install .bat^).
  pause
  exit /b 1
)
echo Checking whether IvyeaOps is already running ...
powershell -NoProfile -Command "try{ $r=Invoke-WebRequest 'http://127.0.0.1:8001/api/health' -TimeoutSec 2 -UseBasicParsing; if($r.StatusCode -eq 200){exit 0} }catch{}; exit 1"
if %errorlevel% equ 0 (
  echo IvyeaOps is ALREADY running. Opening browser ...
  start "" http://127.0.0.1:8001
  echo You can close this window.
  timeout /t 3 >/dev/null
  exit /b 0
)
echo ============================================
echo   Starting IvyeaOps ...
echo   Browser will open: http://127.0.0.1:8001
echo   Keep this window open = server running. Close it = stop.
echo ============================================
echo.
start "" /b powershell -NoProfile -Command "Start-Sleep 6; Start-Process 'http://127.0.0.1:8001'"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8001
echo.
echo [Server stopped]
echo If you saw WinError 10048, port 8001 is used by another instance. Fix:
echo   netstat -ano ^| findstr :8001     then     taskkill /PID ^<pid^> /F
pause
