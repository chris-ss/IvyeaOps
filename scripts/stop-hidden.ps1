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

# 兜底扫杀：IvyeaOpsServer.exe(PyInstaller onedir)会有子进程/worker(终端会话、
# ivyea-agent 等)也加载 _internal\*.pyd —— 只按 PID/端口杀会漏掉它们，导致更新时
# robocopy 复制 DLL 报错误 32(文件占用)。按进程名把残留的全部结束。
try {
    $all = Get-Process -Name IvyeaOpsServer -ErrorAction SilentlyContinue
    if ($all) {
        $all | Stop-Process -Force -ErrorAction SilentlyContinue
        $Stopped = $true
    }
} catch {}

if ($Stopped) {
    Write-Host "[IvyeaOps] Background service stopped." -ForegroundColor Green
} else {
    Write-Host "[IvyeaOps] No running background service found." -ForegroundColor Yellow
}
