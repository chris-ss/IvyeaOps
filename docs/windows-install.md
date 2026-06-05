# IvyeaOps · Windows 部署指南

一份给 Windows 用户的「从零跑起来」教程。拿到的是 IvyeaOps 的源码压缩包（GitHub Download ZIP，约 4 MB），按下面步骤来即可。整套约 5–10 分钟。

> IvyeaOps 是一个自托管的运营工作台，跑在你自己的电脑/服务器上，浏览器访问。数据都在本地。

---

## 一、先装两个运行环境（只需一次）

1. **Python 3.10 或更高**
   - 下载：<https://www.python.org/downloads/>
   - ⚠️ 安装时**第一屏务必勾选「Add python.exe to PATH」**，再点 Install。

2. **Node.js 18 LTS 或更高**（自带 npm）
   - 下载：<https://nodejs.org/>（选 LTS 版）
   - 一路下一步默认安装即可。

装完后，**重新打开**一个 PowerShell 窗口，分别输入下面两行确认（能显示版本号就成功）：

```powershell
python --version
node --version
```

---

## 二、解压 + 一键安装

1. 把压缩包**解压**出来，得到一个文件夹（名字大概是 `IvyeaOps-main`）。
2. 打开这个文件夹，在顶部**地址栏**输入 `powershell` 后回车 —— 会在该目录打开 PowerShell 窗口。
3. 粘贴运行一键安装脚本：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
   ```

   脚本会自动完成：安装 Python 依赖 → 安装前端依赖并构建 → 生成配置文件 `server\.env`。
   **过程中会让你输入一个「管理员密码」**（之后登录网页用，自己随便设一个，记住即可）。

---

## 三、启动并打开

安装完成后，在同一个 PowerShell 窗口里运行：

```powershell
cd server
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

看到类似 `Uvicorn running on http://127.0.0.1:8001` 后，浏览器打开：

**http://127.0.0.1:8001**

用刚才设置的管理员密码登录。首次进入会有「首启向导」，引导你填各类 API 密钥（领星 / 生图等都填你自己申请的）。

> 想关闭服务：回到 PowerShell 窗口按 `Ctrl + C`。
> 下次启动：重新打开 PowerShell，`cd` 到 `IvyeaOps-main\server`，再跑一遍上面那条 `python -m uvicorn ...` 命令即可（不用再装一次）。

---

## 四、常见问题

| 现象 | 解决 |
|---|---|
| 提示 `python 不是内部或外部命令` | Python 没加进 PATH。重装 Python，**勾选「Add to PATH」**；或重开 PowerShell 再试。 |
| 提示 `npm 不是命令` | Node.js 没装好或没重开窗口。重装 Node，重开 PowerShell。 |
| 运行脚本报 `禁止运行脚本 / ExecutionPolicy` | 用本文给的 `powershell -ExecutionPolicy Bypass -File ...` 完整命令运行即可绕过。 |
| 提示端口 `8001` 被占用 | 把命令里的 `--port 8001` 换成别的，比如 `--port 8010`，访问地址也相应改成 `:8010`。 |
| 想重新设管理员密码 | 删除 `server\.env` 文件，重新跑一次 `install.ps1`。 |

---

## 五、说明

- **API 密钥需自己申请填写**（领星、生图等）。在网页「系统配置」里填，密钥只存在你本地。
- **「服务器终端」板块在 Windows 上用不了**（PTY 限制），其余所有板块（智能体会话、领星 ERP、市场调研、Listing、生图、GBrain 知识库等）都正常。
- **可选：用 Docker** —— 如果装了 Docker Desktop，也可以不走脚本：在文件夹里 `copy .env.example .env`，然后 `docker compose up -d`，访问 http://localhost:8080。但上面的原生脚本更省事、免装 Docker。
