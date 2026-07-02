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

# 兜底：`IvyeaOpsServer.exe agent-serve`(:8765) 也是 IvyeaOpsServer.exe——只按 PID/端口8001 杀会
# 漏掉它，导致"停止并退出"后仍残留一个 IvyeaOpsServer.exe 进程。按映像名(/IM)补杀所有实例
# （不加 /T，避免连带杀掉本停止脚本自己）。
try { & taskkill /F /IM IvyeaOpsServer.exe 2>$null | Out-Null; $Stopped = $true } catch {}

if ($Stopped) {
    Write-Host "[IvyeaOps] Background service stopped." -ForegroundColor Green
} else {
    Write-Host "[IvyeaOps] No running background service found." -ForegroundColor Yellow
}
