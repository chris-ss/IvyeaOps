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

# 兜底扫杀：IvyeaOpsServer.exe 会 spawn `IvyeaOpsServer.exe agent-serve`(:8765) 也加载
# _internal\*.pyd。用 `taskkill /F /IM`(**不加 /T**！)按映像名杀掉所有 IvyeaOpsServer.exe——
# 本停止脚本的 PowerShell 是后端 spawn 的子进程，`/T`(整树)会把正在跑的 PowerShell 及其
# taskkill 子进程一起杀掉→杀进程中途中断→agent-serve 反而残留(用户看到的"停止后还有一个
# ivyeaopsserver.exe")。/IM 只按映像名(IvyeaOpsServer.exe)杀，powershell.exe 不匹配→脚本存活跑完。
try { & taskkill /F /IM IvyeaOpsServer.exe 2>$null | Out-Null; $Stopped = $true } catch {}
try {
    $all = Get-Process -Name IvyeaOpsServer -ErrorAction SilentlyContinue
    if ($all) { $all | Stop-Process -Force -ErrorAction SilentlyContinue; $Stopped = $true }
} catch {}

if ($Stopped) {
    Write-Host "[IvyeaOps] Background service stopped." -ForegroundColor Green
} else {
    Write-Host "[IvyeaOps] No running background service found." -ForegroundColor Yellow
}
