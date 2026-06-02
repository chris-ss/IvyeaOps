import { useEffect, useRef, useState } from "react";
import { AgentMessage, AgentSession, listMessages, sendChat, updateSession } from "../api/agents";
import { api } from "../api/client";

type Props = {
  session: AgentSession;
  showCli?: boolean;
  showInherited?: boolean;
};

// Chat-bubble pane.  Renders user / assistant text turns; collapses noisy
// cli_frame messages into a "▾ 终端片段" expandable.  Streams the agent's
// reply via the SSE generator from api/agents.ts.
export default function ChatPane({ session, showCli = false, showInherited = false }: Props) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [input, setInput] = useState("");
  const [partial, setPartial] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const attachRef = useRef<HTMLInputElement>(null);
  const [attachments, setAttachments] = useState<string[]>([]);
  // true = user is near bottom, auto-scroll should follow; false = user scrolled up
  const pinnedRef = useRef(true);

  const isNearBottom = () => {
    const el = scrollerRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  const scrollToBottom = () => {
    if (scrollerRef.current)
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
  };

  const refresh = async () => {
    try {
      const r = await listMessages(session.id, { includeCli: true });
      setMessages(r.messages);
    } catch (e: any) {
      setError(e?.message || "加载消息失败");
    }
  };

  useEffect(() => {
    pinnedRef.current = true;
    setMessages([]);
    setPartial("");
    refresh();
    // Pre-fill input if a pending context message was stored by another page
    const pendingKey = `opshub-pending-msg-${session.id}`;
    const pending = sessionStorage.getItem(pendingKey);
    if (pending) {
      sessionStorage.removeItem(pendingKey);
      setInput(pending);
      setTimeout(() => {
        if (textareaRef.current) {
          textareaRef.current.focus();
          textareaRef.current.setSelectionRange(0, 0);
          textareaRef.current.scrollTop = 0;
        }
      }, 150);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.id]);

  useEffect(() => {
    if (pinnedRef.current) scrollToBottom();
  }, [messages, partial]);

  const submit = async () => {
    const content = input.trim();
    if (!content || streaming) return;
    // Attachments are sent structurally (images become real multimodal blocks
    // for claude; other agents get the paths appended server-side).
    const sentAttachments = attachments;
    setInput("");
    setAttachments([]);
    setStreaming(true);
    setError(null);
    setPartial("");
    pinnedRef.current = true;

    // Auto-name session on first user message if title looks like default
    const isDefaultTitle = !session.title || /^(新会话|.+ 会话)$/.test(session.title);
    if (isDefaultTitle && messages.filter(m => m.role === "user").length === 0) {
      const autoTitle = content.slice(0, 30) + (content.length > 30 ? "…" : "");
      try { await updateSession(session.id, { title: autoTitle }); } catch {}
    }

    let acc = "";
    try {
      for await (const ev of sendChat(session.id, content, { attachments: sentAttachments })) {
        if (ev.type === "user_message") {
          setMessages((prev) => [...prev, ev.payload]);
        } else if (ev.type === "token") {
          acc += ev.payload.text;
          setPartial(acc);
        } else if (ev.type === "assistant_message") {
          setPartial("");
          setMessages((prev) => [...prev, ev.payload]);
        } else if (ev.type === "tool_call" || ev.type === "tool_result") {
          // Structured agentic events (claude stream-json): drop them in-line
          // so the tool call + its result render between text turns.
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
      {/* Scroller */}
      <div ref={scrollerRef} className="chat-body" style={{ display: "flex", flexDirection: "column" }}
        onScroll={() => { pinnedRef.current = isNearBottom(); }}>
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
            ref={textareaRef}
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

const TOOL_GLYPHS: Record<string, string> = {
  Edit: "✏️", MultiEdit: "✏️", Write: "📝", Read: "📖", Bash: "⌘",
  Glob: "🔍", Grep: "🔍", TodoWrite: "☑", WebFetch: "🌐", WebSearch: "🌐",
  Task: "🤖", NotebookEdit: "📓",
};

function shortPath(p?: string): string {
  if (!p) return "";
  const parts = p.split("/").filter(Boolean);
  return parts.length <= 2 ? p : "…/" + parts.slice(-2).join("/");
}

function DiffView({ oldStr, newStr }: { oldStr?: string; newStr?: string }) {
  return (
    <div className="agent-diff">
      {(oldStr ?? "").split("\n").map((l, i) => (
        <div key={"o" + i} className="diff-line diff-del">- {l}</div>
      ))}
      {(newStr ?? "").split("\n").map((l, i) => (
        <div key={"n" + i} className="diff-line diff-add">+ {l}</div>
      ))}
    </div>
  );
}

function TodoView({ todos }: { todos: any[] }) {
  return (
    <div className="agent-todo">
      {todos.map((t, i) => {
        const status = t?.status || "pending";
        const mark = status === "completed" ? "☑" : status === "in_progress" ? "▶" : "☐";
        const label = t?.content || t?.activeForm || "";
        return (
          <div key={i} className={"todo-item todo-" + status}>
            <span className="todo-mark">{mark}</span>
            <span className="todo-text">{label}</span>
          </div>
        );
      })}
    </div>
  );
}

// One-line summary of the most relevant arg, shown next to the tool name.
function toolSummary(name: string, input: any): string {
  if (!input || typeof input !== "object") return "";
  switch (name) {
    case "Bash": return input.command || "";
    case "Read": case "Edit": case "MultiEdit": case "Write": case "NotebookEdit":
      return shortPath(input.file_path);
    case "Glob": case "Grep": return input.pattern || "";
    case "WebFetch": case "WebSearch": return input.url || input.query || "";
    case "Task": return input.description || "";
    default: return "";
  }
}

// Rich detail body per tool type (null = no expandable detail).
function toolDetail(name: string, input: any): React.ReactNode {
  if (!input || typeof input !== "object") {
    return input != null ? <pre className="agent-tool-input">{String(input)}</pre> : null;
  }
  if ((name === "Edit" || name === "MultiEdit") && (input.old_string || input.new_string)) {
    return <DiffView oldStr={input.old_string} newStr={input.new_string} />;
  }
  if (name === "Write" && typeof input.content === "string") {
    return <DiffView newStr={input.content} />;
  }
  if (name === "TodoWrite" && Array.isArray(input.todos)) {
    return <TodoView todos={input.todos} />;
  }
  return <pre className="agent-tool-input">{JSON.stringify(input, null, 2)}</pre>;
}

function ToolCallCard({ m }: { m: AgentMessage }) {
  const name = m.meta?.name || m.content || "工具";
  const input = m.meta?.input;
  const isTodo = name === "TodoWrite" && Array.isArray(input?.todos);
  // Todo lists are most useful expanded by default; everything else collapsed.
  const [open, setOpen] = useState(isTodo);
  const glyph = TOOL_GLYPHS[name] || "🔧";
  const summary = toolSummary(name, input);
  const detail = toolDetail(name, input);

  return (
    <div className="agent-tool-call">
      <button className="agent-tool-head" onClick={() => detail && setOpen((o) => !o)} disabled={!detail}>
        <span className="agent-tool-icon">{glyph}</span>
        <span className="agent-tool-name">{name}</span>
        {summary && <span className="agent-tool-summary">{summary}</span>}
        {detail && <span className="agent-tool-toggle">{open ? "▾" : "▸"}</span>}
      </button>
      {open && detail}
    </div>
  );
}

function ToolResultCard({ m }: { m: AgentMessage }) {
  const isError = !!m.meta?.is_error;
  const text = m.content || "";
  const long = text.length > 400;
  const [open, setOpen] = useState(!long);
  const shown = open ? text : text.slice(0, 400);
  return (
    <div className={"agent-tool-result" + (isError ? " err" : "")}>
      <div className="agent-tool-result-head">
        <span>{isError ? "⚠ 工具错误" : "▣ 结果"}</span>
        {long && (
          <button onClick={() => setOpen((o) => !o)}>{open ? "收起" : "展开全部"}</button>
        )}
      </div>
      {text && <pre>{shown}{!open && long ? "\n…" : ""}</pre>}
    </div>
  );
}

function ThinkingCard({ m }: { m: AgentMessage }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="agent-thinking">
      <button className="agent-thinking-head" onClick={() => setOpen((o) => !o)}>
        <span>💭 思考过程</span>
        <span className="agent-tool-toggle">{open ? "▾" : "▸"}</span>
      </button>
      {open && <div className="agent-thinking-body">{m.content}</div>}
    </div>
  );
}

function Bubble({ m }: { m: AgentMessage }) {
  const isUser = m.role === "user";
  const isSystem = m.role === "system";
  const isCli = m.kind === "cli_frame";

  if (m.kind === "tool_call") return <ToolCallCard m={m} />;
  if (m.kind === "tool_result") return <ToolResultCard m={m} />;
  if (m.role === "assistant" && m.meta?.thinking) return <ThinkingCard m={m} />;

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

  const atts: string[] = Array.isArray(m.meta?.attachments) ? m.meta.attachments : [];
  return (
    <div className={cls} title={m.inherited ? "继承自父会话" : `seq=${m.seq} · ${m.created_at}`}>
      {isCli && <div className="msg-tag">▣ CLI 输出</div>}
      <div>{m.content}</div>
      {isUser && atts.length > 0 && (
        <div className="agent-msg-attachments">
          {atts.map((a, i) => (
            <span key={i} className="agent-att-chip">📎 {a.split("/").pop()}</span>
          ))}
        </div>
      )}
    </div>
  );
}
