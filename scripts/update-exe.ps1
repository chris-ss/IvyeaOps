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

    # Wait for the old server to FULLY exit AND release IvyeaOpsServer.exe. Two
    # process types must die: the main (port 8001) AND `IvyeaOpsServer.exe agent-serve`
    # (:8765). agent-serve 不占 8001、也不锁主 exe——它只锁 _internal\*.pyd，若像原来那样
    # "端口空+主exe解锁就 break" 会在杀掉 agent-serve *之前* 退出→漏杀→robocopy 复制 DLL 报
    # 错误32→更新失败(用户得手动杀那个残留)。所以：每轮**先**按映像名 taskkill /F /IM 杀掉所有
    # IvyeaOpsServer.exe(**不加 /T**,/T 会连带杀掉本更新脚本自己),**再**判退出——退出条件也纳入
    # "还有没有 IvyeaOpsServer 进程"。**绝不因残留而中止**(那是 v1.1.79 的回归,会杀死后端又不
    # 重启→"等待服务重启超时");等满 15s 仍有残留也照常继续复制+重启(v1.1.78 本就这么干)。
    $ServerExePath = Join-Path $RepoRoot "IvyeaOpsServer.exe"
    for ($i = 0; $i -lt 30; $i++) {
        try { & taskkill /F /IM IvyeaOpsServer.exe 2>$null | Out-Null } catch {}
        $portBusy = $null
        try { $portBusy = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue } catch {}
        $procLeft = $null
        try { $procLeft = Get-Process -Name IvyeaOpsServer -ErrorAction SilentlyContinue } catch {}
        $locked = $false
        if (Test-Path $ServerExePath) {
            try { $fs = [System.IO.File]::Open($ServerExePath, 'Open', 'ReadWrite', 'None'); $fs.Close() }
            catch { $locked = $true }
        }
        if (-not $portBusy -and -not $procLeft -and -not $locked) { break }
        Start-Sleep -Milliseconds 500
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
    Write-Host ""
    Write-Info "Update complete. Data and config were preserved."
} catch {
    Write-Fail $_
} finally {
    try { Remove-Item -Recurse -Force $TempRoot -ErrorAction SilentlyContinue } catch {}
    if ($ZipPathParam) { try { Remove-Item -Force $ZipPathParam -ErrorAction SilentlyContinue } catch {} }
    try { Stop-Transcript | Out-Null } catch {}
}
