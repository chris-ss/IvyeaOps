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

# Also kill `IvyeaOpsServer.exe agent-serve` (:8765) -- it is an IvyeaOpsServer.exe
# too, so a PID/port-8001-only stop misses it, leaving one IvyeaOpsServer.exe behind
# after "stop and exit". Kill every instance by image name (/IM, WITHOUT /T so we
# don't tree-kill this stop script itself).
try { & taskkill /F /IM IvyeaOpsServer.exe 2>$null | Out-Null; $Stopped = $true } catch {}

if ($Stopped) {
    Write-Host "[IvyeaOps] Background service stopped." -ForegroundColor Green
} else {
    Write-Host "[IvyeaOps] No running background service found." -ForegroundColor Yellow
}
