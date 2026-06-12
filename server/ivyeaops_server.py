"""PyInstaller-friendly IvyeaOps backend launcher."""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _desktop_paths() -> list[Path]:
    paths: list[Path] = []
    for raw in (
        os.environ.get("USERPROFILE", "") and os.path.join(os.environ["USERPROFILE"], "Desktop"),
        os.path.expandvars(r"%OneDrive%\Desktop"),
        os.path.expandvars(r"%PUBLIC%\Desktop"),
    ):
        if raw and "%" not in raw:
            p = Path(raw)
            if p.exists() and p not in paths:
                paths.append(p)
    return paths


def _write_credentials(root: Path, password: str) -> Path:
    credentials = "\n".join(
        [
            "IvyeaOps 本机登录信息",
            "",
            "访问地址: http://127.0.0.1:8001",
            "用户名: admin",
            f"密码: {password}",
            "",
            "首次登录后可在 系统配置 -> 账号安全 修改密码。",
            "请只保存在自己的电脑上，不要发给他人。",
        ]
    )
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    cred_file = data_dir / "IvyeaOps 登录信息.txt"
    cred_file.write_text(credentials, encoding="utf-8")
    for desktop in _desktop_paths():
        try:
            (desktop / "IvyeaOps 登录信息.txt").write_text(credentials, encoding="utf-8")
        except Exception:
            pass
    return cred_file


def _create_desktop_shortcut(root: Path) -> None:
    if not sys.platform.startswith("win") or not getattr(sys, "frozen", False):
        return
    exe = Path(sys.executable).resolve()
    ps = r"""
$ErrorActionPreference = 'SilentlyContinue'
$Target = $env:IVYEA_SHORTCUT_TARGET
$WorkDir = $env:IVYEA_SHORTCUT_WORKDIR
$Candidates = @()
try { $Candidates += [Environment]::GetFolderPath('Desktop') } catch {}
try { $Candidates += (New-Object -ComObject WScript.Shell).SpecialFolders.Item('Desktop') } catch {}
if ($env:OneDrive) { $Candidates += (Join-Path $env:OneDrive 'Desktop') }
if ($env:PUBLIC) { $Candidates += (Join-Path $env:PUBLIC 'Desktop') }
$Candidates = $Candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
foreach ($Desktop in $Candidates) {
  try {
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut((Join-Path $Desktop 'IvyeaOps.lnk'))
    $Shortcut.TargetPath = $Target
    $Shortcut.WorkingDirectory = $WorkDir
    $Shortcut.Description = '启动 IvyeaOps 工作台'
    $Shortcut.IconLocation = $Target
    $Shortcut.Save()
    break
  } catch {}
}
"""
    env = {**os.environ, "IVYEA_SHORTCUT_TARGET": str(exe), "IVYEA_SHORTCUT_WORKDIR": str(root)}
    try:
        kwargs = {}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            env=env,
            cwd=str(root),
            timeout=15,
            **kwargs,
        )
    except Exception:
        pass


def _open_text_file(path: Path) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception:
        pass


def _already_running(host: str, port: int) -> bool:
    health_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with urllib.request.urlopen(f"http://{health_host}:{port}/api/health", timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


def _control_window_enabled() -> bool:
    return (
        getattr(sys, "frozen", False)
        and sys.platform.startswith("win")
        and os.getenv("IVYEA_OPS_CONTROL_WINDOW", "1").lower() not in {"0", "false", "no"}
    )


def _bootstrap_frozen_env() -> None:
    if not getattr(sys, "frozen", False):
        return
    root = _runtime_root()
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None:
        sys.stdout = (logs_dir / "ivyeaops.out.log").open("a", encoding="utf-8", buffering=1)
    if sys.stderr is None:
        sys.stderr = (logs_dir / "ivyeaops.err.log").open("a", encoding="utf-8", buffering=1)
    # When a console *is* attached (the control window), it defaults to the
    # system code page (GBK on 中文 Windows). Printing the app's Chinese log
    # lines then raises UnicodeEncodeError and can crash startup — force UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass

    env_file = root / "server" / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("ADMIN_PASSWORD="):
                    _write_credentials(root, line.split("=", 1)[1])
                    break
        except Exception:
            pass
        _create_desktop_shortcut(root)
        return

    password = os.getenv("IVYEA_OPS_ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
    secret = secrets.token_urlsafe(32)
    (root / "server").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "\n".join(
            [
                "# Generated by IvyeaOpsServer.exe on first run.",
                "IVYEA_OPS_HOST=127.0.0.1",
                "IVYEA_OPS_PORT=8001",
                "IVYEA_OPS_DEV=0",
                f"IVYEA_OPS_SECRET={secret}",
                "IVYEA_OPS_USER=admin",
                f"ADMIN_PASSWORD={password}",
                "IVYEA_OPS_ALLOWED_ORIGINS=http://127.0.0.1:8001",
                "",
            ]
        ),
        encoding="utf-8",
    )
    cred_file = _write_credentials(root, password)
    _create_desktop_shortcut(root)
    _open_text_file(cred_file)


_bootstrap_frozen_env()

from app.core.config import settings
from app.core.version import app_version
from app.main import app


def _open_browser_when_ready() -> None:
    browser_host = "127.0.0.1" if settings.host in {"0.0.0.0", "::"} else settings.host
    url = f"http://{browser_host}:{settings.port}"
    health_url = f"{url}/api/health"
    for _ in range(40):
        try:
            with urllib.request.urlopen(health_url, timeout=1) as resp:
                if resp.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.5)
    webbrowser.open(url)


def _run_with_control_window() -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:
        uvicorn.run(app, host=settings.host, port=settings.port)
        return

    browser_host = "127.0.0.1" if settings.host in {"0.0.0.0", "::"} else settings.host
    url = f"http://{browser_host}:{settings.port}"
    config = uvicorn.Config(app, host=settings.host, port=settings.port)
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, name="ivyeaops-server", daemon=True)

    root = tk.Tk()
    root.title("IvyeaOps")
    root.geometry("440x252")
    root.resizable(False, False)
    try:
        root.iconbitmap(str(_runtime_root() / "client" / "public" / "favicon.ico"))
    except Exception:
        pass

    # Match the workbench dark theme (client/src/styles/workbench.css):
    # near-black bg, #141414 panel, #262626 border, #4ade80 green accent.
    bg = "#0c0c0c"
    panel = "#141414"
    border = "#262626"
    fg = "#e8e8e8"
    muted = "#a8a8a8"
    faint = "#747474"
    green = "#4ade80"
    green_dim = "#22c55e"
    amber = "#fbbf24"
    btn_dark = "#1c1c1c"
    btn_dark_hover = "#262626"
    ui = "Microsoft YaHei UI"
    mono = "Consolas"
    root.configure(bg=bg)

    frame = tk.Frame(root, bg=panel, padx=24, pady=18,
                     highlightbackground=border, highlightthickness=1)
    frame.pack(fill="both", expand=True, padx=14, pady=14)

    # Header: ASCII-ish brand mark + status dot, workbench console vibe.
    header = tk.Frame(frame, bg=panel)
    header.pack(fill="x")
    tk.Label(header, text="IVYEA OPS", bg=panel, fg=fg,
             font=(mono, 15, "bold")).pack(side="left")
    tk.Label(header, text="CONSOLE", bg=panel, fg=faint,
             font=(mono, 9)).pack(side="left", padx=(8, 0), pady=(5, 0))
    dot_var = tk.StringVar(value="●")
    dot = tk.Label(header, textvariable=dot_var, bg=panel, fg=amber, font=(ui, 11))
    dot.pack(side="right")

    status_var = tk.StringVar(value="正在启动服务…")
    tk.Label(frame, textvariable=status_var, bg=panel, fg=muted,
             font=(ui, 10), pady=6).pack(anchor="w")

    # Divider
    tk.Frame(frame, bg=border, height=1).pack(fill="x", pady=(2, 10))

    # Info rows: monospace, address clickable.
    info = tk.Frame(frame, bg=panel)
    info.pack(fill="x")

    def _row(label: str) -> tk.Frame:
        r = tk.Frame(info, bg=panel)
        r.pack(fill="x", pady=1)
        tk.Label(r, text=label, bg=panel, fg=faint, width=6, anchor="w",
                 font=(mono, 9)).pack(side="left")
        return r

    r1 = _row("地址")
    link = tk.Label(r1, text=url, bg=panel, fg=green, cursor="hand2",
                    font=(mono, 9, "underline"))
    link.pack(side="left")
    r2 = _row("版本")
    tk.Label(r2, text=app_version(), bg=panel, fg=muted, font=(mono, 9)).pack(side="left")
    tk.Label(frame, text="关闭此窗口将停止 IvyeaOps 后台服务", bg=panel, fg=faint,
             font=(ui, 8)).pack(anchor="w", pady=(8, 10))

    buttons = tk.Frame(frame, bg=panel)
    buttons.pack(fill="x", side="bottom")

    stopping = False

    def open_browser() -> None:
        webbrowser.open(url)

    link.bind("<Button-1>", lambda _e: open_browser())

    def stop_server() -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        status_var.set("正在停止服务…")
        dot.configure(fg=faint)
        server.should_exit = True

        def finish() -> None:
            server_thread.join(timeout=8)
            root.after(0, root.destroy)

        threading.Thread(target=finish, daemon=True).start()

    def on_close() -> None:
        stop_server()

    def _styled_btn(parent, text, command, *, primary: bool) -> tk.Button:
        b = tk.Button(
            parent, text=text, command=command, relief="flat", bd=0,
            cursor="hand2", padx=18, pady=7,
            bg=green_dim if primary else btn_dark,
            fg="#04150a" if primary else fg,
            activebackground=green if primary else btn_dark_hover,
            activeforeground="#04150a" if primary else fg,
            font=(ui, 9, "bold") if primary else (ui, 9),
        )
        hover_in = green if primary else btn_dark_hover
        hover_out = green_dim if primary else btn_dark
        b.bind("<Enter>", lambda _e: b.configure(bg=hover_in))
        b.bind("<Leave>", lambda _e: b.configure(bg=hover_out))
        return b

    _styled_btn(buttons, "打开控制台", open_browser, primary=True).pack(side="left")
    _styled_btn(buttons, "停止并退出", stop_server, primary=False).pack(side="left", padx=(10, 0))

    root.protocol("WM_DELETE_WINDOW", on_close)
    server_thread.start()
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    def poll() -> None:
        if stopping:
            return
        if server_thread.is_alive():
            if _already_running(settings.host, settings.port):
                status_var.set("服务运行中，可在浏览器中使用。")
                dot.configure(fg=green)
            else:
                status_var.set("正在启动服务…")
                dot.configure(fg=amber)
            root.after(1000, poll)
            return
        status_var.set("服务已停止。")
        dot.configure(fg="#f87171")
        messagebox.showwarning("IvyeaOps", "IvyeaOps 服务已停止。如需排错，请查看 logs\\ivyeaops.err.log。")
        root.destroy()

    root.after(1000, poll)
    root.mainloop()
    if server_thread.is_alive() and not server.should_exit:
        server.should_exit = True
        server_thread.join(timeout=8)


if __name__ == "__main__":
    if getattr(sys, "frozen", False) and _already_running(settings.host, settings.port):
        browser_host = "127.0.0.1" if settings.host in {"0.0.0.0", "::"} else settings.host
        webbrowser.open(f"http://{browser_host}:{settings.port}")
        sys.exit(0)
    if _control_window_enabled():
        _run_with_control_window()
        sys.exit(0)
    if getattr(sys, "frozen", False) and os.getenv("IVYEA_OPS_SERVER_OPEN_BROWSER", "1") != "0":
        threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    uvicorn.run(app, host=settings.host, port=settings.port)
