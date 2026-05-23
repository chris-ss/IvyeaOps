"""Tiny systemd sd_notify helper.

We talk to systemd directly over the NOTIFY_SOCKET unix datagram socket
instead of pulling in the systemd-python C extension — the protocol is
trivial and avoids an extra build dep on the host.

Use:

    from app.services.watchdog import notify_ready, watchdog_loop

    # in lifespan:
    notify_ready()
    task = asyncio.create_task(watchdog_loop())
    yield
    task.cancel()

If the process is running outside systemd (e.g. local `python -m uvicorn`
during development), `NOTIFY_SOCKET` is unset and all helpers no-op.
"""
from __future__ import annotations

import asyncio
import os
import socket


def _send(msg: str) -> bool:
    sock_path = os.environ.get("NOTIFY_SOCKET")
    if not sock_path:
        return False
    # Linux abstract namespace sockets start with '@', the protocol uses
    # a leading null byte instead.
    if sock_path.startswith("@"):
        sock_path = "\0" + sock_path[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(msg.encode("utf-8"), sock_path)
        return True
    except OSError:
        return False


def notify_ready() -> bool:
    """Tell systemd the service is up. Safe to call any number of times."""
    return _send("READY=1")


def notify_watchdog() -> bool:
    """Send a single WATCHDOG=1 ping. No-op outside systemd."""
    return _send("WATCHDOG=1")


def notify_status(text: str) -> bool:
    """Set the Status= line shown in `systemctl status`."""
    return _send(f"STATUS={text}")


def _watchdog_period_seconds() -> float | None:
    """Return half of WatchdogSec (the ping interval), or None if absent."""
    raw = os.environ.get("WATCHDOG_USEC")
    if not raw:
        return None
    try:
        usec = int(raw)
    except ValueError:
        return None
    if usec <= 0:
        return None
    # Ping at ~1/3 of the deadline so two missed pings still leave slack.
    # systemd's documented recommendation is "at least twice as often as
    # WatchdogSec", we go faster.
    return max(1.0, usec / 1_000_000.0 / 3.0)


async def watchdog_loop() -> None:
    """Async ticker that keeps the systemd watchdog satisfied.

    Cancellable: callers should cancel the task on shutdown so the
    loop exits cleanly. If `WATCHDOG_USEC` isn't set (running outside
    systemd) the coroutine returns immediately.
    """
    period = _watchdog_period_seconds()
    if period is None:
        return
    while True:
        notify_watchdog()
        try:
            await asyncio.sleep(period)
        except asyncio.CancelledError:
            return
