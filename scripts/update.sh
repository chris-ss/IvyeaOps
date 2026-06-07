#!/usr/bin/env bash
# Update IvyeaOps to the latest code — WITHOUT touching your data or config.
#
# Safe by design: git pull only updates tracked code. Your server/.env, the
# data/ directory (all *.sqlite3 DBs + hub_settings.json + uploads) and
# ~/.hermes/skill-studio/ are gitignored / outside the repo, so they are never
# overwritten. install.sh also skips .env when it already exists.
#
# Usage:
#   bash scripts/update.sh
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; RESET="\033[0m"
info() { echo -e "${GREEN}[IvyeaOps]${RESET} $*"; }
warn() { echo -e "${YELLOW}[IvyeaOps]${RESET} $*"; }
die()  { echo -e "${RED}[IvyeaOps] ERROR${RESET} $*" >&2; exit 1; }

[ -d .git ] || die "这不是 git 仓库（你可能是下载的 ZIP）。请改用 git clone 安装后再用本脚本更新，或重新下载最新 ZIP 覆盖代码（注意别覆盖 server/.env 和 data/）。"

info "拉取最新代码（你的 server/.env 与 data/ 数据不会被改动）..."
if ! git pull --ff-only; then
  die "git pull 失败：可能你本地改过被追踪的文件，或有冲突。
     先用  git stash   暂存本地改动，再重跑本脚本；
     或   git status   查看冲突后处理。"
fi

info "刷新依赖并重建前端（复用安装脚本；自动跳过可选安装项，不重生成 .env）..."
# install.sh 幂等：.venv/.env 存在则复用、跳过；更新 pip 依赖、重建前端
# （含国内镜像自动检测、小内存自动加 swap）。 </dev/null 让可选项提示取到 EOF 自动跳过。
bash scripts/install.sh </dev/null

echo
info "更新完成 ✓  数据与配置原样保留。现在重启服务使新代码生效："
echo "    • systemd 部署：   sudo systemctl restart ivyea-ops"
echo "    • 脚本启动的：     在运行窗口按 Ctrl+C 停掉，再  bash scripts/start.sh"
