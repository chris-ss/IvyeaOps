@echo off
title IvyeaOps (LAN Share)
rem Force Python UTF-8 mode so reading UTF-8/中文 config & log files never hits a
rem GBK decode error on 中文 Windows (default code page cp936).
set PYTHONUTF8=1
cd /d "%~dp0server"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Not installed yet. Run the installer first ^(double-click the install .bat^).
  pause
  exit /b 1
)

echo Detecting this computer's LAN IP address ...
set "LANIP="
rem Primary: the adapter that actually has a default gateway (the real LAN card)
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "$c=Get-NetIPConfiguration ^| Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq 'Up' } ^| Select-Object -First 1; if($c){ ($c.IPv4Address ^| Select-Object -First 1).IPAddress }"`) do set "LANIP=%%i"
rem Fallback: first non-loopback, non-APIPA IPv4
if not defined LANIP (
  for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } ^| Select-Object -First 1).IPAddress"`) do set "LANIP=%%i"
)
if not defined LANIP (
  echo [ERROR] Could not detect a LAN IP. Are you connected to Wi-Fi / Ethernet?
  pause
  exit /b 1
)
echo   LAN IP = %LANIP%

rem --- Bind to ALL interfaces + let this LAN origin past the CSRF guard ---
rem    These env vars override server\.env (load_dotenv does not override env).
set "IVYEA_OPS_HOST=0.0.0.0"
set "IVYEA_OPS_ALLOWED_ORIGINS=http://127.0.0.1:8001,http://localhost:8001,http://%LANIP%:8001"

rem --- Windows Firewall: allow inbound TCP 8001 (best-effort, asks UAC once) ---
echo Checking Windows Firewall rule for port 8001 ...
netsh advfirewall firewall show rule name="IvyeaOps8001" >nul 2>&1
if errorlevel 1 (
  echo   Adding firewall rule ^(a UAC prompt may pop up - click Yes^) ...
  powershell -NoProfile -Command "try{ Start-Process netsh -Verb RunAs -WindowStyle Hidden -Wait -ArgumentList @('advfirewall','firewall','add','rule','name=IvyeaOps8001','dir=in','action=allow','protocol=TCP','localport=8001') }catch{ exit 1 }"
  if errorlevel 1 echo   [WARN] Firewall rule not added. If other devices cannot connect, add an inbound rule for TCP port 8001 manually, or run this file as Administrator once.
) else (
  echo   Firewall rule already present.
)

echo Checking whether IvyeaOps is already running ...
powershell -NoProfile -Command "try{ $r=Invoke-WebRequest 'http://127.0.0.1:8001/api/health' -TimeoutSec 2 -UseBasicParsing; if($r.StatusCode -eq 200){exit 0} }catch{}; exit 1"
if %errorlevel% equ 0 (
  echo.
  echo [NOTE] IvyeaOps is ALREADY running - probably only on 127.0.0.1.
  echo        For LAN sharing, close that other window first, then run THIS file.
  echo.
)

echo ============================================================
echo   IvyeaOps - LAN SHARE MODE
echo.
echo   This computer  : http://127.0.0.1:8001
echo   Other devices  : http://%LANIP%:8001
echo.
echo   ^>^> On any phone or PC in the SAME network, just open a
echo      browser and visit:   http://%LANIP%:8001
echo      (nothing to install on those devices)
echo.
echo   Keep this window OPEN = server running. Close it = stop.
echo   If your LAN IP changes later, just run this file again.
echo ============================================================
echo.
start "" /b powershell -NoProfile -Command "Start-Sleep 6; Start-Process 'http://127.0.0.1:8001'"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8001
echo.
echo [Server stopped]
echo If you saw WinError 10048, port 8001 is already in use. Fix:
echo   netstat -ano ^| findstr :8001     then     taskkill /PID ^<pid^> /F
pause
