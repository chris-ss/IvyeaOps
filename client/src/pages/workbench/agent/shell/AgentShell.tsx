import { useMemo, useRef, useState } from "react";
import { AgentSession, cliWebSocketUrl } from "../../../../api/agents";
import XtermActionToolbar from "../../../../components/XtermActionToolbar";
import {
  enableNativeSelectionMode,
  getSelectedTerminalText,
  getVisibleTerminalText,
} from "../../../../components/xtermSelection";
import { useShellTerminal } from "./useShellTerminal";
import { useShellSocket, type ShellConnState } from "./useShellSocket";
import { useEffect } from "react";

type Props = {
  session: AgentSession;
};

/**
 * Right-pane terminal view for an agent session.
 *
 * Composition:
 *   useShellTerminal — owns xterm.js (Terminal + addons + DOM events)
 *   useShellSocket   — owns the WebSocket lifecycle + reconnect
 *
 * The two hooks share refs via this view (terminalRef, wsRef) instead of
 * tangling their effects, which is the pattern that makes the
 * claudecodeui shell stable: each hook has a single concern and a clean
 * teardown.
 */
export default function AgentShell({ session }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const feedbackTimerRef = useRef<number | null>(null);

  const flash = (msg: string) => {
    if (feedbackTimerRef.current) window.clearTimeout(feedbackTimerRef.current);
    setFeedback(msg);
    feedbackTimerRef.current = window.setTimeout(() => setFeedback(null), 1600);
  };

  useEffect(() => () => {
    if (feedbackTimerRef.current) window.clearTimeout(feedbackTimerRef.current);
  }, []);

  const { terminalRef, fitNow } = useShellTerminal({
    containerRef,
    wsRef,
    inputBlocked: selectMode,
  });

  const url = useMemo(() => cliWebSocketUrl(session.id), [session.id]);
  const { state, reconnect } = useShellSocket({
    url,
    terminalRef,
    wsRef,
    onMessage: () => {
      // Re-fit when first output arrives — some terminals only know their
      // real char size after a glyph paint.
      if (terminalRef.current && terminalRef.current.buffer.active.length <= 1) {
        fitNow();
      }
    },
  });

  // Native-selection mode: temporarily make text selectable, suspend input.
  useEffect(() => {
    const host = containerRef.current;
    if (!host || !selectMode) return;
    return enableNativeSelectionMode(host);
  }, [selectMode]);

  const copyText = async (text: string, emptyHint: string) => {
    if (!text) { flash(emptyHint); return; }
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        window.prompt("复制以下内容：", text);
      }
      flash("已复制");
    } catch {
      window.prompt("复制以下内容：", text);
      flash("已打开复制窗口");
    }
  };

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (!text) { flash("剪贴板为空"); return; }
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "input", data: text }));
      }
      flash("已粘贴");
    } catch {
      flash("浏览器拒绝了剪贴板读取");
    }
  };

  return (
    <div className={"agent-shell" + (selectMode ? " select-mode" : "")}>
      <div className="agent-shell-bar">
        <ConnStatus state={state} onReconnect={reconnect} />
        <span className="agent-shell-meta">
          agent={session.agent_id} · model={session.model || "-"}
        </span>
        {feedback && <span className="xterm-feedback">{feedback}</span>}
        <XtermActionToolbar
          selectMode={selectMode}
          onToggleSelectMode={() => {
            setSelectMode((prev) => {
              const next = !prev;
              flash(next ? "已进入复制模式" : "已恢复输入模式");
              return next;
            });
          }}
          onCopySelection={() => copyText(getSelectedTerminalText(terminalRef.current), "暂无选中文本")}
          onCopyVisible={() => copyText(getVisibleTerminalText(containerRef.current), "当前屏幕没有可复制内容")}
          onPaste={handlePaste}
        />
      </div>
      <div ref={containerRef} className="agent-shell-host" />
      <ConnBanner state={state} onReconnect={reconnect} />
    </div>
  );
}

// ─── Status pieces ─────────────────────────────────────────────────────────

function ConnStatus({ state, onReconnect }: { state: ShellConnState; onReconnect: () => void }) {
  switch (state.kind) {
    case "open":
      return <span className="agent-shell-status live">● 已连接</span>;
    case "connecting":
      return <span className="agent-shell-status pending">○ 连接中…</span>;
    case "reconnecting":
      return (
        <span className="agent-shell-status pending">
          ○ 重连中 (第 {state.attempt} 次，{(state.nextInMs / 1000).toFixed(0)}s 后)
          <button className="tbtn" onClick={onReconnect} style={{ marginLeft: 6 }}>立即重试</button>
        </span>
      );
    case "closed":
      return (
        <span className="agent-shell-status dead">
          ○ 已断开 · {state.reason || ""}
          <button className="tbtn" onClick={onReconnect} style={{ marginLeft: 6 }}>↻ 重连</button>
        </span>
      );
    case "fatal":
      return <span className="agent-shell-status err">⚠ {state.reason}</span>;
    case "idle":
    default:
      return <span className="agent-shell-status pending">○ 待连接</span>;
  }
}

function ConnBanner({ state, onReconnect }: { state: ShellConnState; onReconnect: () => void }) {
  // Inline banner inside the host area only for fatal errors — too noisy
  // otherwise.
  if (state.kind !== "fatal") return null;
  return (
    <div className="agent-shell-banner">
      <span>⚠ {state.reason}</span>
      <button className="tbtn" onClick={onReconnect}>重试</button>
    </div>
  );
}
