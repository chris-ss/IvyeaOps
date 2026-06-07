# IvyeaOps · 自托管亚马逊运营工作台

**IvyeaOps** 是一套**开源、自托管**的亚马逊运营工作台：一台服务器、一次登录，把
Listing 制作、AI 生图、市场调研、深度分析、广告优化（含领星 ERP 接入）、AI 智能体、
GBrain 知识库、Skill 工坊、服务器运维等运营全流程，统一收进浏览器里。

> 数据与密钥都留在你自己的服务器，不绑定任何第三方云。MIT 协议，可自由二次开发。

- **技术栈**：后端 FastAPI（Python）+ 前端 React / Vite（TypeScript），后端直接托管前端构建产物。
- **支持平台**：Linux / macOS（完整）· Windows（除 PTY 终端外完整）。
- **默认端口**：`8001`（`http://127.0.0.1:8001`）。
- **仓库**：<https://github.com/Hector-xue/IvyeaOps>

---

## 目录

- [核心特性](#核心特性)
- [功能板块总览](#功能板块总览)
- [快速开始](#快速开始)
- [配置模型（两层）](#配置模型两层)
- [AI 智能体](#ai-智能体)
- [领星 ERP 接入](#领星-erp-接入)
- [生产环境部署（Linux）](#生产环境部署linux)
- [项目结构](#项目结构)
- [更新与维护](#更新与维护)
- [安全须知](#安全须知)
- [许可证](#许可证)

---

## 核心特性

- **本地部署**：跑在自己的服务器，不依赖第三方 SaaS，业务数据不出私域。
- **数据安全**：店铺数据、API 密钥统一存放在后端 `data/`（已 gitignore），不入代码库、不暴露给前端或智能体。
- **开箱即用**：一条安装命令检测依赖、构建前端、生成 `.env`，约几分钟即可访问；内置首启向导。
- **可二次开发**：MIT 开源，前后端按模块拆分，路由 / 服务一一对应，新增板块成本低。
- **一次登录，全部模块**：单点登录后侧边栏直达所有板块，统一主题（内置 10 套配色）。
- **智能体驱动**：浏览器内直接跑 Claude / hermes 智能体，支持流式输出、会话续聊、工具可视化。

---

## 功能板块总览

> 📖 **每个板块怎么用、需要哪些配置，详见使用手册 [`docs/USAGE.md`](docs/USAGE.md)。**

侧边栏按四组组织，与下表一一对应：

### 工具
| 板块 | 说明 |
|---|---|
| 🏠 **首页** | 工作台概览与常用入口 |
| 🔍 **市场调研** | 关键词 / 竞品 / 类目洞察，结合数据源 + AI 综合分析 |
| 🎯 **打法推荐** | 按品类给出运营策略建议 |
| 📝 **Listing 工作台** | ASIN → 标题 · 五点 · 描述；AI 文案与改写 |
| 🧪 **分析工具（深度分析）** | 竞品速查 · 关键词竞争 · Listing 重写 · 评论聚类 · 流量诊断 |
| 📦 **领星 ERP** | 经官方 OpenAPI 接入领星：数据浏览 / 大盘 / 广告优化引擎 / 自动化建议 / 受控写操作 / 审计（见下文专章） |
| ✦ **Skill 中心 / 想法工坊** | 一句话生成 Skill（多阶段严谨生成 + 自检修复）、Tool Spec 可视化、执行历史、审核制一键修复 |

### AI & 系统
| 板块 | 说明 |
|---|---|
| 💬 **AI 问答** | 浏览器内通用 AI 问答助手 |
| 🖼 **AI 生图** | Prompt → 批量主图 / 场景图（图像工作流） |
| 🤖 **智能体会话** | 原生移植 claudecodeui 体验：Claude 走 stream-json 结构化输出、会话 resume、工具调用可视化、终端 |
| 🧠 **GBrain 知识库** | 私有 Markdown 笔记 + 语义检索（embedding） |
| 💻 **服务器终端** | 浏览器内 PTY 多终端会话（仅 Linux） |
| 📊 **服务器监控** | CPU / 进程 / 日志等资源一屏掌握，含告警 |

### 小工具
| 板块 | 说明 |
|---|---|
| 🚢 **头程比价** | 头程运费比价 |

### 管理
| 板块 | 说明 |
|---|---|
| 👥 **用户管理** | 多用户与权限 |
| ⚙️ **系统配置** | 集中式运行时配置（密钥 / 集成路径 / 阈值），首启向导引导 |
| 📰 **资讯** | 每日 AI 行业资讯摘要 |

> 还内置「审核制 AI 自动修复」（功能报错时用 hermes + git worktree 隔离生成修复、人工审核后应用，默认关闭）等运维能力。

---

## 快速开始

### Linux / macOS

```bash
# 1. 克隆
git clone https://github.com/Hector-xue/IvyeaOps.git
cd IvyeaOps

# 2. 一键安装（检测依赖、构建前端、生成 .env）
bash scripts/install.sh

# 3. 启动
bash scripts/start.sh
```

浏览器打开 **http://127.0.0.1:8001**，首启向导会引导你完成智能体检测与 API 密钥设置。

> **🇨🇳 国内网络加速**
> - **克隆慢**：用 gh 代理 `git clone https://gh-proxy.com/https://github.com/Hector-xue/IvyeaOps.git`；或用 Gitee 镜像（最稳，见仓库说明）。
> - **装依赖慢**：`install.sh` / `install.ps1` 会**自动检测**是否在大陆网络，自动把 pip、npm 切到清华 + 淘宝镜像（无需手动；可用 `IVYEA_CN=1` 强制开、`IVYEA_CN=0` 关）。
> - **hermes / GBrain 慢**：这两个是境外安装器，可选、可稍后单独重试；镜像环境变量会顺带加速它们内部的 pip/npm 步骤。

> macOS 与 Linux 命令完全一致（同为 Unix）：原生脚本和 `docker compose up -d` 都可用，
> PTY 终端也正常工作。需先有 Python 3.9+ 与 Node 18+（可用 Homebrew 安装）。

### Windows（双击即装、双击即用）

下载 ZIP 解压后：

1. **双击「安装 IvyeaOps.bat」** —— 自动检测/安装 Python+Node（缺则 winget 自动装）、
   装依赖、构建前端、生成配置、并在**桌面创建「IvyeaOps」快捷方式**，最后可直接启动。
2. 以后**双击桌面「IvyeaOps」**（或「启动 IvyeaOps.bat」）—— 服务自动起、浏览器自动
   打开 **http://127.0.0.1:8001**，像启动一个软件一样。

> 喜欢命令行也可以：`powershell -ExecutionPolicy Bypass -File scripts\install.ps1`。
>
> **注意**：Windows 不支持 PTY 多终端会话，其余功能正常。
>
> 📖 从零开始的 Windows 图文步骤（含环境安装与常见问题排查）见
> [`docs/windows-install.md`](docs/windows-install.md)，适合直接转发给非开发的同事。

### 环境要求

| | Linux | Windows |
|---|---|---|
| Python | 3.9+ | 3.9+ |
| Node.js | 18+ | 18+ |
| npm | 随 Node 安装 | 随 Node 安装 |

---

## 配置模型（两层）

IvyeaOps 采用两层配置：

**第一层 · 启动配置（`server/.env`）**：仅启动时读取一次。
必填：`IVYEA_OPS_SECRET`、`IVYEA_OPS_PASSWORD_HASH`、`IVYEA_OPS_ALLOWED_ORIGINS`。
由 `install.sh` / `install.ps1` 自动生成。

**第二层 · 运行时配置（`data/hub_settings.json`）**：在网页「系统配置」里编辑。
存放各类 API 密钥、集成路径、告警阈值等。留空时自动回退到对应的 `IVYEA_OPS_*` 环境变量，
再回退到内置默认值。该文件已 gitignore，不入代码库。

> 完整配置项参考 [`docs/CONFIG.md`](docs/CONFIG.md)。

---

## AI 智能体

IvyeaOps 支持在浏览器里直接调用本地智能体 CLI，至少安装一个即可：

| 智能体 | 说明 |
|---|---|
| **Claude** | 「智能体会话」原生移植 claudecodeui，走 stream-json 结构化输出，支持会话 resume、工具调用可视化 |
| **hermes** | 文本类任务的主力，模型默认 deepseek（主）+ mimo（兜底）；含 MCP、飞书中继等能力 |
| **codex** *(可选)* | OpenAI Codex CLI；如不再使用可忽略 |

安装后 IvyeaOps 会从 `$PATH` 自动探测，多数情况下无需手动配置路径。

---

## 领星 ERP 接入

「领星 ERP」板块经领星**官方 OpenAPI**把店铺数据与广告操作接入工作台，覆盖三类需求，
并以**自建网关作唯一咽喉**做安全隔离：

- **浏览分析**：数据浏览 / 大盘 / 多店铺对比，只读拉取真实经营与广告数据。
- **优化引擎**：确定性**规则引擎**产出否词 / 出价 / 加词等建议（数据不足不动手），LLM 仅复核。
- **自动化建议**：定时分析产出优化建议（仅建议，不直接写入）。
- **受控写操作**：默认**双开关全关**；开启后写操作强制**三重复核 + 确定性护栏 + 人工确认**，
  执行前抓回滚快照、失败自动熔断、全程审计。

> 详细使用说明见 [`docs/lingxing-erp-guide.md`](docs/lingxing-erp-guide.md)，或板块内「帮助」tab。
> 凭证（AppID / AppSecret 等）写入后端 `data/hub_settings.json`，不入代码库。

---

## 生产环境部署（Linux）

生产环境推荐 nginx 反向代理 + Let's Encrypt + systemd：

```bash
cp deploy/install.conf.example deploy/install.conf
$EDITOR deploy/install.conf   # 设置 SERVER_NAME、INSTALL_DIR 等
bash scripts/render-deploy.sh
# 按打印出的 sudo cp 指引落地 nginx / systemd 配置
```

服务以 systemd 单元 `ivyea-ops` 运行（监听 :8001，托管 `client/dist`）。
完整指南见 [`docs/INSTALL.md`](docs/INSTALL.md)，可选集成见 [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md)。

---

## 项目结构

```
IvyeaOps/
├── server/                FastAPI 后端（Python）
│   ├── app/
│   │   ├── core/          配置、设置、安全、集成
│   │   ├── routers/       每个功能一个路由（lingxing / brain / market / listing / agent_hub …）
│   │   ├── services/      各功能的业务逻辑
│   │   └── agents/        智能体（providers / projects 等）
│   ├── .env.example
│   └── requirements.txt
├── client/                React + Vite 前端（TypeScript）
│   └── src/
│       ├── pages/workbench/   各工作台板块
│       ├── agents/            「智能体会话」原生移植子应用
│       ├── components/        通用组件
│       ├── layouts/           侧边栏 / 主框架
│       └── api/               类型化 API 客户端
├── data/                  运行时数据（SQLite、hub_settings.json）— gitignore
├── deploy/                nginx / systemd / cron / docker 模板
├── scripts/
│   ├── install.sh         Linux 一键安装
│   ├── install.ps1        Windows 一键安装
│   ├── build.sh           仅重建前端
│   ├── dev.sh             本地开发（Vite + uvicorn）
│   └── render-deploy.sh   渲染生产部署配置
└── docs/
    ├── CONFIG.md          完整配置参考
    ├── INSTALL.md         生产部署指南
    ├── INTEGRATIONS.md    可选集成
    └── lingxing-erp-guide.md  领星 ERP 使用文档
```

---

## 更新与维护

```bash
git pull
bash scripts/install.sh           # 重装依赖并重建前端
sudo systemctl restart ivyea-ops  # Linux + systemd 下重启服务
```

- 仅改前端：`bash scripts/build.sh`（或 `cd client && npm run build`），浏览器硬刷新即可。
- 改后端：需重启 `ivyea-ops` 服务。

---

## 安全须知

- `server/.env`、`data/`（含 `hub_settings.json`、领星凭证、SQLite）、`saved-images/` 均已 gitignore，**切勿**提交。
- 迁移 / 改前缀时务必原样保留 `IVYEA_OPS_SECRET` 与 `IVYEA_OPS_PASSWORD_HASH`，否则会登录 401。
- 领星等真实店铺写操作受双开关 + 三重复核 + 人工确认保护，请勿绕过。

---

## 许可证

MIT
