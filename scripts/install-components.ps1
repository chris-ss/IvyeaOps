# IvyeaOps optional component installer (Windows / PowerShell 5.1+)
#
# Components:
#   hermes  - official Hermes Agent installer
#   gbrain  - Bun + GBrain CLI + ~/brain initialization
#   codex   - Node.js + OpenAI Codex CLI
#   claude  - Node.js + Claude Code CLI
#   all     - hermes + gbrain

param(
    [ValidateSet("all", "hermes", "gbrain", "codex", "claude", "status")]
    [string]$Component = "all"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[IvyeaOps] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[IvyeaOps] 注意: $msg" -ForegroundColor Yellow }
function Test-Cmd($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $extras = @(
        "$env:USERPROFILE\.bun\bin",
        "$env:USERPROFILE\.hermes\bin",
        "$env:USERPROFILE\.hermes\node\bin",
        "$env:USERPROFILE\.ivyeaops\node",
        "$env:USERPROFILE\.local\bin"
    )
    $env:Path = (($extras + $machine + $user) -join ";")
}

function Show-Status {
    Refresh-Path
    $hermes = Get-Command hermes -ErrorAction SilentlyContinue
    $bun = Get-Command bun -ErrorAction SilentlyContinue
    $gbrain = Get-Command gbrain -ErrorAction SilentlyContinue
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    $codex = Get-Command codex -ErrorAction SilentlyContinue
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    Write-Host "Hermes: $(if ($hermes) { $hermes.Source } else { '未安装' })"
    Write-Host "Bun:    $(if ($bun) { $bun.Source } else { '未安装' })"
    Write-Host "GBrain: $(if ($gbrain) { $gbrain.Source } else { '未安装' })"
    Write-Host "Node:   $(if ($node) { $node.Source } else { '未安装' })"
    Write-Host "npm:    $(if ($npm) { $npm.Source } else { '未安装' })"
    Write-Host "Codex:  $(if ($codex) { $codex.Source } else { '未安装' })"
    Write-Host "Claude: $(if ($claude) { $claude.Source } else { '未安装' })"
    Write-Host "Brain:  $env:USERPROFILE\brain"
}

function Add-UserPath($dir) {
    if (-not (Test-Path $dir)) { return }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @()
    if ($userPath) { $parts = $userPath -split ";" | Where-Object { $_ } }
    if ($parts -notcontains $dir) {
        [Environment]::SetEnvironmentVariable("Path", (($parts + $dir) -join ";"), "User")
    }
    Refresh-Path
}

function Install-UserNode {
    Refresh-Path
    if (Test-Cmd "npm") {
        Write-Info "npm 已安装：$((Get-Command npm).Source)"
        return
    }

    Write-Info "未找到 npm，安装用户级 Node.js LTS（无需管理员权限）..."
    $arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
    if (($env:PROCESSOR_ARCHITECTURE -eq "ARM64") -or ($env:PROCESSOR_ARCHITEW6432 -eq "ARM64")) { $arch = "arm64" }

    $base = "https://nodejs.org/dist/latest-v22.x"
    $sum = Invoke-RestMethod "$base/SHASUMS256.txt"
    $zipName = (($sum -split "`n") | ForEach-Object {
        if ($_ -match "(node-v[0-9.]+-win-$arch\.zip)") { $Matches[1] }
    } | Select-Object -First 1)
    if (-not $zipName) { throw "无法从 nodejs.org 找到 Windows $arch 的 Node.js LTS zip。" }

    $tmp = Join-Path $env:TEMP $zipName
    $targetRoot = "$env:USERPROFILE\.ivyeaops"
    $nodeDir = Join-Path $targetRoot "node"
    $extractDir = Join-Path $targetRoot "node-extract"
    if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
    New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
    Invoke-WebRequest "$base/$zipName" -OutFile $tmp
    Expand-Archive -Path $tmp -DestinationPath $extractDir -Force

    $expanded = Get-ChildItem $extractDir -Directory | Select-Object -First 1
    if (-not $expanded) { throw "Node.js 解压失败。" }
    if (Test-Path $nodeDir) { Remove-Item -Recurse -Force $nodeDir }
    Move-Item $expanded.FullName $nodeDir
    Remove-Item -Recurse -Force $extractDir
    Add-UserPath $nodeDir

    if (-not (Test-Cmd "npm")) { throw "Node.js 已解压，但仍未找到 npm。请重开 IvyeaOps 后重试。" }
    Write-Info "Node.js 安装完成：$((Get-Command node).Source)"
}

function Install-NpmPackage($commandName, $packageName) {
    Refresh-Path
    if (Test-Cmd $commandName) {
        Write-Info "$commandName 已安装：$((Get-Command $commandName).Source)"
        return
    }
    Install-UserNode
    Refresh-Path
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) { throw "未找到 npm，无法安装 $commandName。" }
    Write-Info "安装/更新 $commandName：$packageName"
    & $npm.Source install -g $packageName
    if ($LASTEXITCODE -ne 0) { throw "npm install -g $packageName 失败。" }
    Refresh-Path
    if (-not (Test-Cmd $commandName)) {
        Write-Warn "$commandName 已安装，但当前会话暂未发现命令。请重开 IvyeaOps 或重新检测。"
    } else {
        Write-Info "$commandName 安装完成：$((Get-Command $commandName).Source)"
    }
}

function Install-Hermes {
    Refresh-Path
    if (Test-Cmd "hermes") {
        Write-Info "Hermes 已安装：$((Get-Command hermes).Source)"
        return
    }
    Write-Info "安装 Hermes Agent（官方 Windows 安装器）..."
    Invoke-Expression (Invoke-RestMethod "https://hermes-agent.nousresearch.com/install.ps1")
    Refresh-Path
    if (Test-Cmd "hermes") {
        Write-Info "Hermes 安装完成：$((Get-Command hermes).Source)"
    } else {
        Write-Warn "Hermes 安装器已运行，但当前会话暂未发现 hermes 命令。请重开 IvyeaOps 或重新检测。"
    }
}

function Install-GBrain {
    Refresh-Path
    if (-not (Test-Cmd "bun")) {
        Write-Info "安装 Bun（GBrain 需要）..."
        Invoke-Expression (Invoke-RestMethod "https://bun.sh/install.ps1")
        $env:Path = "$env:USERPROFILE\.bun\bin;" + $env:Path
        Refresh-Path
    } else {
        Write-Info "Bun 已安装：$((Get-Command bun).Source)"
    }

    $bun = Get-Command bun -ErrorAction SilentlyContinue
    if (-not $bun) {
        $fallback = "$env:USERPROFILE\.bun\bin\bun.exe"
        if (Test-Path $fallback) { $bun = Get-Item $fallback }
    }
    if (-not $bun) { throw "未找到 bun，无法安装 GBrain。" }

    Write-Info "安装/更新 GBrain..."
    & $bun.Source install -g github:garrytan/gbrain
    if ($LASTEXITCODE -ne 0) { throw "bun install -g github:garrytan/gbrain 失败。" }
    Refresh-Path

    $gbrain = Get-Command gbrain -ErrorAction SilentlyContinue
    if (-not $gbrain) {
        $fallback = "$env:USERPROFILE\.bun\bin\gbrain.exe"
        if (Test-Path $fallback) { $gbrain = Get-Item $fallback }
    }
    if (-not $gbrain) { throw "GBrain 安装后仍未找到 gbrain 命令。" }

    $brain = "$env:USERPROFILE\brain"
    if (-not (Test-Path $brain)) { New-Item -ItemType Directory -Path $brain | Out-Null }
    Push-Location $brain
    try { & $gbrain.Source init --pglite 2>$null } catch { Write-Warn "gbrain init 可稍后重试：$_" }
    Pop-Location
    Write-Info "GBrain 安装完成：$($gbrain.Source)"
    Write-Info "Brain Root：$brain"
}

if ($Component -eq "status") { Show-Status; exit 0 }
if ($Component -eq "all" -or $Component -eq "hermes") { Install-Hermes }
if ($Component -eq "all" -or $Component -eq "gbrain") { Install-GBrain }
if ($Component -eq "codex") { Install-NpmPackage "codex" "@openai/codex" }
if ($Component -eq "claude") { Install-NpmPackage "claude" "@anthropic-ai/claude-code" }
Show-Status
