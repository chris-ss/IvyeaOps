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

    # ── Light, rounded, borderless "card" window ────────────────────────────
    # Clean high-end look: no native title bar, a rounded light card (transparent
    # corners via the Windows -transparentcolor key), custom drag + close.
    W, H, RADIUS = 460, 268, 18
    KEY = "#ff00ff"        # transparency key (won't appear in the UI)
    card = "#fbfbf9"       # light card bg
    sub = "#f1f1ee"        # subtle row / button bg
    sub_hi = "#e8e8e4"
    border = "#e2e2dd"
    fg = "#1a1a1a"
    muted = "#5b5b55"
    faint = "#9a9a93"
    green = "#16a34a"
    green_hi = "#15803d"
    amber = "#d97706"
    red = "#dc2626"
    ui = "Microsoft YaHei UI"
    mono = "Consolas"

    root = tk.Tk()
    root.title("IvyeaOps")
    root.resizable(False, False)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 3}")

    rounded = False
    try:
        root.overrideredirect(True)        # borderless
        root.attributes("-transparentcolor", KEY)
        rounded = True
    except Exception:
        rounded = False
    try:
        root.attributes("-topmost", False)
        root.iconbitmap(str(_runtime_root() / "client" / "public" / "favicon.ico"))
    except Exception:
        pass

    canvas = tk.Canvas(root, width=W, height=H, highlightthickness=0, bd=0,
                       bg=KEY if rounded else card)
    canvas.pack(fill="both", expand=True)

    def _round_rect(c, x1, y1, x2, y2, r, fill):
        c.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, width=0)
        c.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, width=0)
        for (ax, ay, start) in ((x1, y1, 90), (x2 - 2 * r, y1, 0),
                                (x1, y2 - 2 * r, 180), (x2 - 2 * r, y2 - 2 * r, 270)):
            c.create_arc(ax, ay, ax + 2 * r, ay + 2 * r, start=start, extent=90,
                         style="pieslice", fill=fill, width=0)

    # 1px border ring (slightly larger card behind the fill), then the card.
    if rounded:
        _round_rect(canvas, 0, 0, W, H, RADIUS, fill=border)
        _round_rect(canvas, 1, 1, W - 1, H - 1, RADIUS - 1, fill=card)
    else:
        canvas.configure(bg=card)

    # Content lives in a frame floated over the rounded card.
    frame = tk.Frame(canvas, bg=card)
    canvas.create_window(W // 2, H // 2, window=frame, width=W - 44, height=H - 40)

    stopping = False

    def open_browser() -> None:
        webbrowser.open(url)

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

    # Title bar: brand + status dot + custom close. Draggable to move the window.
    header = tk.Frame(frame, bg=card)
    header.pack(fill="x")
    brand = tk.Label(header, text="IvyeaOps", bg=card, fg=fg, font=(ui, 14, "bold"))
    brand.pack(side="left")
    close_btn = tk.Label(header, text="✕", bg=card, fg=faint, cursor="hand2",
                         font=(ui, 11))
    close_btn.pack(side="right", padx=(6, 0))
    close_btn.bind("<Button-1>", lambda _e: stop_server())
    close_btn.bind("<Enter>", lambda _e: close_btn.configure(fg=red))
    close_btn.bind("<Leave>", lambda _e: close_btn.configure(fg=faint))
    dot = tk.Label(header, text="●", bg=card, fg=amber, font=(ui, 11))
    dot.pack(side="right")

    # Drag the window by the header / brand (borderless has no native title bar).
    _drag = {"x": 0, "y": 0}

    def _drag_start(e):
        _drag["x"], _drag["y"] = e.x, e.y

    def _drag_move(e):
        root.geometry(f"+{root.winfo_x() + e.x - _drag['x']}+{root.winfo_y() + e.y - _drag['y']}")

    for w in (header, brand):
        w.bind("<Button-1>", _drag_start)
        w.bind("<B1-Motion>", _drag_move)

    status_var = tk.StringVar(value="正在启动服务…")
    tk.Label(frame, textvariable=status_var, bg=card, fg=muted, anchor="w",
             font=(ui, 10)).pack(fill="x", pady=(8, 8))

    tk.Frame(frame, bg=border, height=1).pack(fill="x", pady=(0, 10))

    def _row(label: str) -> tk.Frame:
        r = tk.Frame(frame, bg=card)
        r.pack(fill="x", pady=1)
        tk.Label(r, text=label, bg=card, fg=faint, width=5, anchor="w",
                 font=(mono, 9)).pack(side="left")
        return r

    r1 = _row("地址")
    link = tk.Label(r1, text=url, bg=card, fg=green, cursor="hand2",
                    font=(mono, 10, "underline"))
    link.pack(side="left")
    link.bind("<Button-1>", lambda _e: open_browser())
    link.bind("<Enter>", lambda _e: link.configure(fg=green_hi))
    link.bind("<Leave>", lambda _e: link.configure(fg=green))
    r2 = _row("版本")
    tk.Label(r2, text=app_version(), bg=card, fg=muted, font=(mono, 9)).pack(side="left")

    tk.Label(frame, text="关闭窗口将停止后台服务", bg=card, fg=faint,
             font=(ui, 8)).pack(anchor="w", pady=(10, 12))

    buttons = tk.Frame(frame, bg=card)
    buttons.pack(fill="x", side="bottom")

    def _styled_btn(parent, text, command, *, primary: bool) -> tk.Button:
        b = tk.Button(
            parent, text=text, command=command, relief="flat", bd=0,
            cursor="hand2", padx=18, pady=7,
            bg=green if primary else sub,
            fg="#ffffff" if primary else fg,
            activebackground=green_hi if primary else sub_hi,
            activeforeground="#ffffff" if primary else fg,
            font=(ui, 9, "bold") if primary else (ui, 9),
        )
        hin = green_hi if primary else sub_hi
        hout = green if primary else sub
        b.bind("<Enter>", lambda _e: b.configure(bg=hin))
        b.bind("<Leave>", lambda _e: b.configure(bg=hout))
        return b

    _styled_btn(buttons, "打开控制台", open_browser, primary=True).pack(side="left")
    _styled_btn(buttons, "停止并退出", stop_server, primary=False).pack(side="left", padx=(10, 0))

    root.protocol("WM_DELETE_WINDOW", stop_server)
    server_thread.start()
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    def poll() -> None:
        if stopping:
            return
        if server_thread.is_alive():
            if _already_running(settings.host, settings.port):
                status_var.set("服务运行中，可在浏览器中使用")
                dot.configure(fg=green)
            else:
                status_var.set("正在启动服务…")
                dot.configure(fg=amber)
            root.after(1000, poll)
            return
        status_var.set("服务已停止")
        dot.configure(fg=red)
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
