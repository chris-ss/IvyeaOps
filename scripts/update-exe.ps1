# IvyeaOps Windows x64 one-click updater.
#
# Safe update for GitHub Release ZIP installs:
#   1. stop the background server
#   2. download the latest IvyeaOps-Windows-x64.zip
#   3. copy new program files over the current folder
#   4. keep user data/config: data\, logs\, server\.env
#   5. restart IvyeaOpsServer.exe

param(
    [string]$DownloadUrl = "https://github.com/Hector-xue/IvyeaOps/releases/latest/download/IvyeaOps-Windows-x64.zip",
    # Pre-downloaded bundle (the in-app updater downloads with live progress and
    # hands the file here) — skips the Invoke-WebRequest step entirely.
    [string]$ZipPath = "",
    [switch]$NonInteractive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Capture the param before the script reuses $ZipPath as its temp-file variable
# further down (otherwise the param value would be clobbered).
$ZipPathParam = ""
if ($ZipPath -and (Test-Path $ZipPath)) { $ZipPathParam = (Resolve-Path $ZipPath).Path }

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

# Always record the run to logs\update.log. The updater often runs hidden (from
# the .bat / in-app button), so without this a failure leaves no trace and is
# impossible to diagnose. Best-effort: never let logging break the update.
try {
    $LogDir = Join-Path $RepoRoot "logs"
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
    Start-Transcript -Path (Join-Path $LogDir "update.log") -Append -Force | Out-Null
} catch {}

function Write-Info($msg) { Write-Host "[IvyeaOps] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[IvyeaOps] WARN: $msg" -ForegroundColor Yellow }
function Write-Fail($msg) {
    Write-Host "[IvyeaOps] ERROR: $msg" -ForegroundColor Red
    if (-not $NonInteractive -and $env:IVYEAOPS_NONINTERACTIVE -ne "1") {
        Read-Host "Press Enter to exit"
    }
    exit 1
}

function Stop-IvyeaOps {
    $StopScript = Join-Path $RepoRoot "scripts\stop-hidden.ps1"
    if (Test-Path $StopScript) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $StopScript
        return
    }
    try {
        $conn = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue }
    } catch {}
}

function Find-PackageRoot($ExtractDir) {
    $directExe = Join-Path $ExtractDir "IvyeaOpsServer.exe"
    if (Test-Path $directExe) { return $ExtractDir }

    $dirs = Get-ChildItem $ExtractDir -Directory
    foreach ($d in $dirs) {
        if (Test-Path (Join-Path $d.FullName "IvyeaOpsServer.exe")) { return $d.FullName }
    }
    return $null
}

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "  IvyeaOps Windows x64 updater" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Keeps:   data\, logs\, server\.env"
Write-Host "  Updates: program files, frontend, scripts, docs"
Write-Host ""

$EnvFile = Join-Path $RepoRoot "server\.env"
$DataDir = Join-Path $RepoRoot "data"
if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Force -Path $DataDir | Out-Null }

$TempRoot = Join-Path $env:TEMP ("IvyeaOpsUpdate-" + [Guid]::NewGuid().ToString("N"))
$ZipPath = Join-Path $TempRoot "IvyeaOps-Windows-x64.zip"
$ExtractDir = Join-Path $TempRoot "extract"
$EnvBackup = Join-Path $TempRoot "server.env.backup"

try {
    New-Item -ItemType Directory -Force -Path $TempRoot, $ExtractDir | Out-Null
    if (Test-Path $EnvFile) { Copy-Item $EnvFile $EnvBackup -Force }

    Write-Info "Stopping background service..."
    Stop-IvyeaOps

    # Wait for the old server to FULLY exit. IvyeaOpsServer.exe (PyInstaller onedir)
    # spawns child/worker processes (terminal sessions, ivyea-agent, ...) that keep
    # _internal\*.pyd DLLs open — killing only the port-8001 process leaves those,
    # and robocopy then fails with "error 32 (file in use)" on the DLLs. So each
    # iteration also force-kills ANY remaining IvyeaOpsServer process by name.
    $ServerExePath = Join-Path $RepoRoot "IvyeaOpsServer.exe"
    for ($i = 0; $i -lt 30; $i++) {
        $portBusy = $null
        try { $portBusy = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue } catch {}
        $procRunning = $null
        try { $procRunning = Get-Process -Name IvyeaOpsServer -ErrorAction SilentlyContinue } catch {}
        $locked = $false
        if (Test-Path $ServerExePath) {
            try { $fs = [System.IO.File]::Open($ServerExePath, 'Open', 'ReadWrite', 'None'); $fs.Close() }
            catch { $locked = $true }
        }
        if (-not $portBusy -and -not $procRunning -and -not $locked) { break }
        # 残留子进程/worker 仍锁着 _internal\*.pyd —— 强杀。Stop-Process -Force **不杀子进程树**，
        # 而 IvyeaOpsServer.exe 会 spawn `IvyeaOpsServer.exe agent-serve`(:8765) 及终端/agent
        # 子进程；用 taskkill /F /T 按映像名杀掉整棵树(含非同名子进程)，再显式杀 :8765 owner。
        try { & taskkill /F /T /IM IvyeaOpsServer.exe 2>$null | Out-Null } catch {}
        if ($procRunning) { try { $procRunning | Stop-Process -Force -ErrorAction SilentlyContinue } catch {} }
        try {
            $agent = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($agent) { & taskkill /F /T /PID $agent.OwningProcess 2>$null | Out-Null }
        } catch {}
        Start-Sleep -Milliseconds 500
    }

    # 仍有 IvyeaOpsServer 进程 / 端口占用 / exe 被锁，则在动任何文件之前中止。
    # 否则 robocopy 会在被锁的 _internal\*.pyd 上失败（错误 32），且可能已更新前端
    # （client\dist，后端从磁盘读取）却没换后端 —— 留下前端新/后端旧的错配，新路由
    # 缺失，POST 落到 SPA 兜底（仅 GET）→ 405 Method Not Allowed。中止时不改动任何文件。
    $stillBusy = $null
    try { $stillBusy = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue } catch {}
    $stillRunning = $null
    try { $stillRunning = Get-Process -Name IvyeaOpsServer -ErrorAction SilentlyContinue } catch {}
    $stillLocked = $false
    if (Test-Path $ServerExePath) {
        try { $fs = [System.IO.File]::Open($ServerExePath, 'Open', 'ReadWrite', 'None'); $fs.Close() }
        catch { $stillLocked = $true }
    }
    if ($stillBusy -or $stillRunning -or $stillLocked) {
        Write-Fail "无法彻底停止 IvyeaOps（仍有 IvyeaOpsServer 进程 / 端口 8001 占用 / exe 或 _internal 被锁）。这会让 robocopy 在 _internal\*.pyd 上报错误 32（文件占用），并可能留下前端新/后端旧的错配（405）。已中止，未改动任何文件。请在任务管理器结束所有 IvyeaOpsServer.exe（可能有多个子进程）后重试，或先运行：Get-Process IvyeaOpsServer | Stop-Process -Force"
    }

    if ($ZipPathParam) {
        Write-Info "Using pre-downloaded package: $ZipPathParam"
        Copy-Item $ZipPathParam $ZipPath -Force
    } else {
        Write-Info "Downloading latest Windows x64 package..."
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $ZipPath -UseBasicParsing
    }

    Write-Info "Extracting update package..."
    Expand-Archive -Path $ZipPath -DestinationPath $ExtractDir -Force
    # Strip the Mark-of-the-Web (Zone.Identifier) the download carries, so Windows
    # SmartScreen / antivirus do not block the freshly-copied exe or the _internal\
    # DLLs at launch. Best-effort — never let it abort the update.
    try { Get-ChildItem $ExtractDir -Recurse -File | Unblock-File -ErrorAction SilentlyContinue } catch {}
    $PackageRoot = Find-PackageRoot $ExtractDir
    if (-not $PackageRoot) { Write-Fail "Invalid update package: IvyeaOpsServer.exe not found." }

    Write-Info "Copying program files while keeping data and config..."
    $robocopyArgs = @(
        $PackageRoot,
        $RepoRoot,
        "/E",
        "/XD", "data", "logs", ".git",
        "/XF", ".env",
        "/R:2",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NP"
    )
    & robocopy @robocopyArgs | Out-Host
    $rc = $LASTEXITCODE
    if ($rc -gt 7) { Write-Fail "File copy failed, robocopy exit code: $rc" }

    if ((Test-Path $EnvBackup) -and -not (Test-Path $EnvFile)) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $EnvFile) | Out-Null
        Copy-Item $EnvBackup $EnvFile -Force
    }

    $ServerExe = Join-Path $RepoRoot "IvyeaOpsServer.exe"
    if (-not (Test-Path $ServerExe)) { Write-Fail "IvyeaOpsServer.exe not found after update." }

    Write-Info "Starting IvyeaOps..."
    Start-Process -FilePath $ServerExe -WorkingDirectory $RepoRoot | Out-Null

    # 确认新后端真的起来了（否则会出现“前端已更新、后端没起/还是旧的”错配）。
    $up = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            if (Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue) { $up = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    Write-Host ""
    if ($up) {
        Write-Info "Update complete. Backend restarted (port 8001 listening). Data and config were preserved."
    } else {
        Write-Warn "文件已更新，但后端未在 15s 内监听 8001。请手动双击 IvyeaOpsServer.exe 启动；若仍异常，查看 logs\update.log 与后端日志。"
    }
} catch {
    Write-Fail $_
} finally {
    try { Remove-Item -Recurse -Force $TempRoot -ErrorAction SilentlyContinue } catch {}
    if ($ZipPathParam) { try { Remove-Item -Force $ZipPathParam -ErrorAction SilentlyContinue } catch {} }
    try { Stop-Transcript | Out-Null } catch {}
}
