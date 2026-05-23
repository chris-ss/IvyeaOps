import { useEffect, useRef, useState } from "react";
import { AgentMessage, AgentSession, listMessages, sendChat, updateSession } from "../api/agents";
import { api } from "../api/client";

type Props = {
  session: AgentSession;
};

// Chat-bubble pane.  Renders user / assistant text turns; collapses noisy
// cli_frame messages into a "▾ 终端片段" expandable.  Streams the agent's
// reply via the SSE generator from api/agents.ts.
export default function ChatPane({ session }: Props) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [input, setInput] = useState("");
  const [partial, setPartial] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [showCli, setShowCli] = useState(false);
  const [showInherited, setShowInherited] = useState(false);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const attachRef = useRef<HTMLInputElement>(null);
  const [attachments, setAttachments] = useState<string[]>([]);

  const refresh = async () => {
    try {
      const r = await listMessages(session.id, { includeCli: true });
      setMessages(r.messages);
    } catch (e: any) {
      setError(e?.message || "加载消息失败");
    }
  };

  useEffect(() => {
    setMessages([]);
    setPartial("");
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.id]);

  useEffect(() => {
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [messages, partial]);

  const submit = async () => {
    const content = input.trim();
    if (!content || streaming) return;
    // Append attachment paths to the message
    let fullContent = content;
    if (attachments.length > 0) {
      fullContent += "\n\n[附件]\n" + attachments.map(a => `- ${a}`).join("\n");
    }
    setInput("");
    setAttachments([]);
    setStreaming(true);
    setError(null);
    setPartial("");

    // Auto-name session on first user message if title looks like default
    const isDefaultTitle = !session.title || /^(新会话|.+ 会话)$/.test(session.title);
    if (isDefaultTitle && messages.filter(m => m.role === "user").length === 0) {
      const autoTitle = content.slice(0, 30) + (content.length > 30 ? "…" : "");
      try { await updateSession(session.id, { title: autoTitle }); } catch {}
    }

    let acc = "";
    try {
      for await (const ev of sendChat(session.id, fullContent)) {
        if (ev.type === "user_message") {
          setMessages((prev) => [...prev, ev.payload]);
        } else if (ev.type === "token") {
          acc += ev.payload.text;
          setPartial(acc);
        } else if (ev.type === "assistant_message") {
          setPartial("");
          setMessages((prev) => [...prev, ev.payload]);
        } else if (ev.type === "warning") {
          setError(ev.payload.detail);
        } else if (ev.type === "error") {
          setError(ev.payload.detail);
        } else if (ev.type === "auto_compacted") {
          refresh();
        } else if (ev.type === "exit") {
          setError(`Agent 进程退出 (code=${ev.payload.code ?? "?"})`);
        }
      }
    } catch (e: any) {
      setError(e?.message || "请求失败");
    } finally {
      setStreaming(false);
      refresh();
    }
  };

  const visible = messages.filter((m) => {
    if (m.inherited && !showInherited) return false;
    if (m.kind === "summary" && !showInherited) return false;
    if (m.kind === "cli_frame") return showCli;
    return true;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
      {/* Toolbar */}
      <div className="pane-bar">
        <label style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer", color: "var(--t3)" }}>
          <input type="checkbox" checked={showCli} onChange={(e) => setShowCli(e.target.checked)} />
          终端片段
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer", color: "var(--t3)" }}>
          <input type="checkbox" checked={showInherited} onChange={(e) => setShowInherited(e.target.checked)} />
          上下文
        </label>
        <span className="pb-right">
          <span style={{ color: "var(--t3)" }}>token≈ {session.token_estimate}</span>
          <span style={{ color: session.live ? "var(--acc)" : "var(--t3)" }}>
            {session.live ? "● 在线" : "○ 休眠"}
          </span>
        </span>
      </div>

      {/* Scroller */}
      <div ref={scrollerRef} className="chat-body" style={{ display: "flex", flexDirection: "column" }}>
        {visible.length === 0 && !partial && (
          <div style={{ margin: "auto", color: "var(--t3)", fontSize: 11, textAlign: "center", padding: 30 }}>
            <div style={{ fontSize: 26, color: "var(--b2)", marginBottom: 10 }}>🍃</div>
            还没有消息，输入下方文本开始对话
          </div>
        )}
        {visible.map((m) => (
          <Bubble key={m.id} m={m} />
        ))}
        {partial && (
          <Bubble
            m={{
              id: "_partial",
              session_id: session.id,
              seq: -1,
              role: "assistant",
              kind: "text",
              source: "chat",
              content: partial,
              meta: {},
              created_at: new Date().toISOString(),
            }}
          />
        )}
        {streaming && !partial && (
          <div className="agent-msg assistant" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="spin" /> 思考中...
          </div>
        )}
        {error && (
          <div
            style={{
              alignSelf: "stretch",
              marginTop: 8,
              padding: "6px 10px",
              border: "1px solid rgba(248,113,113,.35)",
              background: "rgba(248,113,113,.06)",
              color: "var(--red)",
              fontSize: 10,
              borderRadius: "var(--r)",
            }}
          >
            ⚠ {error}
          </div>
        )}
      </div>

      {/* Composer */}
      <div className="composer-row">
        {attachments.length > 0 && (
          <div className="composer-attachments">
            {attachments.map((a, i) => (
              <span key={i} className="composer-att">
                📎 {a.split("/").pop()}
                <button onClick={() => setAttachments(prev => prev.filter((_, j) => j !== i))}>✕</button>
              </span>
            ))}
          </div>
        )}
        <div className="composer-input-row">
          <button
            className="attach-btn"
            onClick={() => attachRef.current?.click()}
            disabled={streaming}
            title="上传图片或文件"
          >
            📎
          </button>
          <input
            ref={attachRef}
            type="file"
            hidden
            accept="image/*,.pdf,.txt,.md,.csv,.json,.py,.js,.ts,.log"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              try {
                const form = new FormData();
                form.append("file", file);
                const { data } = await api.post("/agent-files/upload", form);
                setAttachments(prev => [...prev, data.path]);
              } catch {
                setError("文件上传失败");
              }
              e.target.value = "";
            }}
          />
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={
              streaming
                ? "等待回复中..."
                : typeof window !== "undefined" && window.matchMedia("(max-width: 680px)").matches
                  ? "输入消息..."
                  : "输入消息（Enter 发送 / Shift+Enter 换行）"
            }
            rows={2}
            disabled={streaming}
          />
          <button className="send-btn" onClick={submit} disabled={streaming || !input.trim()}>
            {streaming ? "..." : "发送 ↵"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Bubble({ m }: { m: AgentMessage }) {
  const isUser = m.role === "user";
  const isSystem = m.role === "system";
  const isCli = m.kind === "cli_frame";

  if (isSystem && m.kind === "summary") {
    return (
      <div className={"agent-msg summary" + (m.inherited ? " inherited" : "")}>
        <div className="msg-tag">◆ 任务摘要</div>
        <div>{m.content}</div>
      </div>
    );
  }

  let cls = "agent-msg ";
  if (isUser) cls += "user";
  else if (isCli) cls += "cli";
  else cls += "assistant";
  if (m.inherited) cls += " inherited";

  return (
    <div className={cls} title={m.inherited ? "继承自父会话" : `seq=${m.seq} · ${m.created_at}`}>
      {isCli && <div className="msg-tag">▣ CLI 输出</div>}
      <div>{m.content}</div>
    </div>
  );
}
