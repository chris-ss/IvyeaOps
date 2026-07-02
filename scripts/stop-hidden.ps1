# Stop the hidden/background IvyeaOps Windows backend.

Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PidFile = Join-Path $RepoRoot "data\ivyeaops.pid"
$Stopped = $false

if (Test-Path $PidFile) {
    try {
        $pidText = (Get-Content $PidFile -Raw).Trim()
        if ($pidText -match '^\d+$') {
            $proc = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
            if ($proc) {
                Stop-Process -Id $proc.Id -Force
                $Stopped = $true
            }
        }
    } finally {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

if (-not $Stopped) {
    $conn = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        $Stopped = $true
    }
}

# 兜底扫杀：IvyeaOpsServer.exe(PyInstaller onedir)会 spawn `IvyeaOpsServer.exe agent-serve`
# (:8765) 及终端/agent 子进程，都加载 _internal\*.pyd —— 只按 PID/端口/进程名 Stop-Process
# 会漏掉子进程树(Stop-Process 不杀子进程)，导致更新时 robocopy 复制 DLL 报错误 32(文件占用)。
# 用 taskkill /F /T 按映像名杀整棵树(含非同名子进程)，再显式杀 :8765 owner。
try { & taskkill /F /T /IM IvyeaOpsServer.exe 2>$null | Out-Null; $Stopped = $true } catch {}
try {
    $all = Get-Process -Name IvyeaOpsServer -ErrorAction SilentlyContinue
    if ($all) { $all | Stop-Process -Force -ErrorAction SilentlyContinue; $Stopped = $true }
} catch {}
try {
    $agent = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($agent) { & taskkill /F /T /PID $agent.OwningProcess 2>$null | Out-Null; $Stopped = $true }
} catch {}

if ($Stopped) {
    Write-Host "[IvyeaOps] Background service stopped." -ForegroundColor Green
} else {
    Write-Host "[IvyeaOps] No running background service found." -ForegroundColor Yellow
}
