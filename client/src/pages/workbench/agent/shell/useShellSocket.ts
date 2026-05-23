import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import { parseShellMessage, sendSocketMessage, type ShellInbound } from "./shellUtils";

export type ShellConnState =
  | { kind: "idle" }
  | { kind: "connecting" }
  | { kind: "open" }
  | { kind: "reconnecting"; attempt: number; nextInMs: number }
  | { kind: "closed"; reason?: string }
  | { kind: "fatal"; reason: string };

type Options = {
  /** Full ws/wss URL of the agent PTY endpoint. */
  url: string;
  /** Returns the live xterm Terminal so output frames can be written directly. */
  terminalRef: MutableRefObject<any>;
  /** External handle to the socket, populated on open / cleared on close. */
  wsRef: MutableRefObject<WebSocket | null>;
  /** Optional callback fired on each parsed inbound message. */
  onMessage?: (msg: ShellInbound) => void;
  /** Whether to auto-(re)connect when the consumer mounts. Default true. */
  autoConnect?: boolean;
};

type Result = {
  state: ShellConnState;
  /** Manually initiate a connect; safe to call any time. */
  connect: () => void;
  /** Manually disconnect; clears the auto-reconnect timer. */
  disconnect: () => void;
  /** Force-reconnect (close+open). */
  reconnect: () => void;
};

const RETRY_BASE_MS = 1000;
const RETRY_MAX_MS = 15_000;
const RETRY_BACKOFF = 1.6;
const HEARTBEAT_MS = 25_000;

/**
 * Manages the agent shell WebSocket with:
 *   - explicit state machine (idle/connecting/open/reconnecting/closed/fatal)
 *   - exponential backoff reconnect (1s → 1.6s → … capped at 15s)
 *   - periodic ping while open so idle proxies don't drop us
 *   - clean teardown on unmount / URL change
 *
 * Output frames are written into the xterm Terminal owned by useShellTerminal;
 * snapshot frames clear the screen first so reconnects don't double-render.
 */
export function useShellSocket({
  url, terminalRef, wsRef, onMessage, autoConnect = true,
}: Options): Result {
  const [state, setState] = useState<ShellConnState>({ kind: "idle" });
  const stateRef = useRef<ShellConnState>(state);
  stateRef.current = state;

  const retryAttemptRef = useRef(0);
  const retryTimerRef = useRef<number | null>(null);
  const heartbeatTimerRef = useRef<number | null>(null);
  const intentionalCloseRef = useRef(false);

  const clearRetry = useCallback(() => {
    if (retryTimerRef.current !== null) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  const clearHeartbeat = useCallback(() => {
    if (heartbeatTimerRef.current !== null) {
      window.clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
  }, []);

  const closeQuietly = useCallback(() => {
    const ws = wsRef.current;
    if (ws) {
      try { ws.close(); } catch { /* ignore */ }
      wsRef.current = null;
    }
    clearHeartbeat();
  }, [clearHeartbeat, wsRef]);

  const open = useCallback(() => {
    if (!url) return;
    // Don't pile up sockets.
    if (wsRef.current && (
      wsRef.current.readyState === WebSocket.OPEN ||
      wsRef.current.readyState === WebSocket.CONNECTING
    )) return;

    intentionalCloseRef.current = false;
    setState({ kind: "connecting" });

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (e: any) {
      setState({ kind: "fatal", reason: e?.message || "WebSocket 创建失败" });
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      retryAttemptRef.current = 0;
      setState({ kind: "open" });
      // Heartbeat keeps idle nginx connections warm.
      heartbeatTimerRef.current = window.setInterval(() => {
        sendSocketMessage(wsRef.current, { type: "ping" });
      }, HEARTBEAT_MS);
    };

    ws.onmessage = (ev) => {
      const raw = typeof ev.data === "string" ? ev.data : String(ev.data ?? "");
      const msg = parseShellMessage(raw);
      if (!msg) return;
      const term = terminalRef.current;
      if (msg.type === "snapshot") {
        // Snapshot is the full visible buffer after reconnect — clear first
        // so we don't stack the old screen on top of the new one.
        if (term) {
          try { term.clear(); term.write("\x1b[2J\x1b[H"); } catch { /* ignore */ }
        }
        if (term && typeof msg.data === "string") term.write(msg.data);
      } else if (msg.type === "output") {
        if (term && typeof msg.data === "string") term.write(msg.data);
      } else if (msg.type === "exit") {
        if (term) {
          term.write(`\r\n\x1b[31m[agent 进程退出 code=${msg.code ?? "?"}]\x1b[0m\r\n`);
        }
      } else if (msg.type === "error") {
        if (term) {
          term.write(`\r\n\x1b[31m[error] ${msg.detail}\x1b[0m\r\n`);
        }
      }
      onMessage?.(msg);
    };

    ws.onclose = (ev) => {
      clearHeartbeat();
      wsRef.current = null;
      if (intentionalCloseRef.current) {
        setState({ kind: "closed", reason: "已断开" });
        return;
      }
      // 4xxx codes from server = auth/not-found, don't retry forever.
      if (ev.code === 4401) {
        setState({ kind: "fatal", reason: "未登录或会话过期，请刷新页面" });
        return;
      }
      if (ev.code === 4404) {
        setState({ kind: "fatal", reason: "会话不存在" });
        return;
      }
      if (ev.code === 4500) {
        setState({ kind: "fatal", reason: "agent 进程启动失败（查看 ops-hub 日志）" });
        return;
      }
      // Network / proxy drop — back off and try again.
      const attempt = retryAttemptRef.current + 1;
      retryAttemptRef.current = attempt;
      const delay = Math.min(RETRY_MAX_MS, RETRY_BASE_MS * Math.pow(RETRY_BACKOFF, attempt - 1));
      setState({ kind: "reconnecting", attempt, nextInMs: delay });
      retryTimerRef.current = window.setTimeout(() => {
        // Re-check we haven't been intentionally torn down in the meantime.
        if (intentionalCloseRef.current) return;
        open();
      }, delay);
    };

    ws.onerror = () => {
      // onclose follows; let it decide state.
    };
  }, [clearHeartbeat, onMessage, terminalRef, url, wsRef]);

  const connect = useCallback(() => {
    intentionalCloseRef.current = false;
    clearRetry();
    open();
  }, [clearRetry, open]);

  const disconnect = useCallback(() => {
    intentionalCloseRef.current = true;
    clearRetry();
    closeQuietly();
    setState({ kind: "closed", reason: "用户断开" });
  }, [clearRetry, closeQuietly]);

  const reconnect = useCallback(() => {
    intentionalCloseRef.current = false;
    clearRetry();
    closeQuietly();
    // Small async gap so the close event lands before we re-open.
    window.setTimeout(open, 80);
  }, [clearRetry, closeQuietly, open]);

  // Mount: auto-connect; Unmount: tear down completely.
  useEffect(() => {
    if (autoConnect) connect();
    return () => {
      intentionalCloseRef.current = true;
      clearRetry();
      closeQuietly();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, autoConnect]);

  return { state, connect, disconnect, reconnect };
}
