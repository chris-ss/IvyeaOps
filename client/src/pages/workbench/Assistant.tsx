import { useEffect, useRef, useState, type MouseEvent } from "react";
import { streamChat, type ChatMsg } from "../../api/assistant";
import { MarkdownReport } from "../../lib/reportFormat";

const STORAGE = "ivyea-ops-assistant-chat";
const SESSIONS_KEY = "ivyea-ops-assistant-sessions";
const CURRENT_ID_KEY = "ivyea-ops-assistant-current-id";
const MAX_SESSIONS = 50;

interface Turn { role: "user" | "assistant"; content: string }
interface Session { id: string; title: string; turns: Turn[]; updatedAt: number }

function loadSessions(): Session[] {
  try { const r = localStorage.getItem(SESSIONS_KEY); if (r) return JSON.parse(r); } catch {}
  return [];
}

function saveSessions(sessions: Session[]) {
  try { localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.slice(0, MAX_SESSIONS))); } catch {}
}

function sessionTitle(turns: Turn[]): string {
  const first = turns.find(t => t.role === "user");
  if (!first) return "新对话";
  return first.content.length > 24 ? first.content.slice(0, 24) + "…" : first.content;
}

export default function Assistant() {
  const [sessions, setSessions] = useState<Session[]>(loadSessions);
  const [currentId, setCurrentId] = useState<string>(() => {
    try { const s = localStorage.getItem(CURRENT_ID_KEY); if (s) return s; } catch {}
    return Date.now().toString();
  });
  const [turns, setTurns] = useState<Turn[]>(() => {
    try { const r = localStorage.getItem(STORAGE); if (r) return JSON.parse(r); } catch {}
    return [];
  });
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [err, setErr] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try { localStorage.setItem(CURRENT_ID_KEY, currentId); } catch {}
  }, [currentId]);

  useEffect(() => {
    try { localStorage.setItem(STORAGE, JSON.stringify(turns.slice(-40))); } catch {}
    if (turns.length === 0) return;
    const session: Session = { id: currentId, title: sessionTitle(turns), turns: turns.slice(-40), updatedAt: Date.now() };
    setSessions(prev => {
      const idx = prev.findIndex(s => s.id === currentId);
      const next = idx >= 0
        ? [...prev.slice(0, idx), session, ...prev.slice(idx + 1)]
        : [session, ...prev];
      saveSessions(next);
      return next;
    });
  }, [turns, currentId]);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [turns, streaming]);

  const send = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setErr("");
    const base: Turn[] = [...turns, { role: "user", content: text }];
    setTurns([...base, { role: "assistant", content: "" }]);
    setInput("");
    setStreaming(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const msgs: ChatMsg[] = [
      { role: "system", content: "你是亚马逊运营助手，用中文清晰作答；需要时用 Markdown（表格/列表/标题）写出可直接复制的文档。" },
      ...base.map(t => ({ role: t.role, content: t.content } as ChatMsg)),
    ];
    try {
      await streamChat(msgs, (e) => {
        if (e.type === "token") {
          setTurns(prev => {
            const n = [...prev];
            n[n.length - 1] = { role: "assistant", content: n[n.length - 1].content + e.text };
            return n;
          });
        } else if (e.type === "error") {
          setErr(e.detail);
        }
      }, ctrl.signal);
    } catch (e: any) {
      if (e?.name !== "AbortError") setErr(e?.message || "请求失败");
    } finally {
      setStreaming(false);
    }
  };

  const stop = () => { abortRef.current?.abort(); setStreaming(false); };

  const startNew = () => {
    if (streaming) return;
    setCurrentId(Date.now().toString());
    setTurns([]);
    setErr("");
    setHistoryOpen(false);
  };

  const loadSession = (s: Session) => {
    if (streaming) return;
    setCurrentId(s.id);
    setTurns(s.turns);
    setErr("");
    setHistoryOpen(false);
  };

  const deleteSession = (id: string, e: MouseEvent) => {
    e.stopPropagation();
    setSessions(prev => {
      const next = prev.filter(s => s.id !== id);
      saveSessions(next);
      return next;
    });
    if (id === currentId) {
      setCurrentId(Date.now().toString());
      setTurns([]);
      setErr("");
    }
  };

  return (
    <div className="market-page asst-page">
      {/* Bottom sheet backdrop */}
      {historyOpen && (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 897, background: "rgba(0,0,0,.5)" }}
          onClick={() => setHistoryOpen(false)}
        />
      )}

      {/* Bottom sheet — always rendered so transition plays on close */}
      <div style={{
        position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 898,
        maxHeight: "62vh", background: "var(--bg1)",
        borderRadius: "16px 16px 0 0",
        display: "flex", flexDirection: "column",
        boxShadow: "0 -4px 32px rgba(0,0,0,.4)",
        transform: historyOpen ? "translateY(0)" : "translateY(110%)",
        transition: "transform .25s cubic-bezier(.4,0,.2,1)",
      }}>
        {/* Drag handle */}
        <div style={{ display: "flex", justifyContent: "center", padding: "10px 0 4px", flexShrink: 0 }}>
          <div style={{ width: 36, height: 4, borderRadius: 2, background: "var(--b2)" }} />
        </div>
        {/* Sheet header */}
        <div style={{ display: "flex", alignItems: "center", padding: "2px 16px 10px", flexShrink: 0, borderBottom: "1px solid var(--b)" }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--t)", flex: 1 }}>历史对话</span>
          <button className="tbtn" onClick={startNew} disabled={streaming} style={{ marginRight: 8 }}>＋ 新对话</button>
          <button
            onClick={() => setHistoryOpen(false)}
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)", fontSize: 18, padding: "0 2px", lineHeight: 1 }}
          >✕</button>
        </div>
        {/* Session list */}
        <div style={{ overflowY: "auto", flex: 1 }}>
          {sessions.length === 0
            ? <div style={{ padding: "28px 16px", fontSize: 13, color: "var(--t3)", textAlign: "center" }}>暂无历史对话</div>
            : sessions.map(s => (
              <div
                key={s.id}
                onClick={() => loadSession(s)}
                style={{
                  padding: "12px 16px", cursor: "pointer", borderBottom: "1px solid var(--b)",
                  background: s.id === currentId ? "color-mix(in srgb, var(--acc) 10%, transparent)" : undefined,
                  display: "flex", alignItems: "center", gap: 10, transition: "background .12s",
                }}
                onMouseEnter={e => { if (s.id !== currentId) (e.currentTarget as HTMLDivElement).style.background = "var(--bg3)"; }}
                onMouseLeave={e => { if (s.id !== currentId) (e.currentTarget as HTMLDivElement).style.background = ""; }}
              >
                <div style={{
                  width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                  background: s.id === currentId ? "color-mix(in srgb, var(--acc) 20%, transparent)" : "var(--bg3)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 14, color: s.id === currentId ? "var(--acc)" : "var(--t3)",
                }}>✦</div>
                <div style={{ flex: 1, overflow: "hidden" }}>
                  <div style={{
                    fontSize: 13, fontWeight: s.id === currentId ? 600 : 400,
                    color: s.id === currentId ? "var(--acc)" : "var(--t)",
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}>{s.title}</div>
                  <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>
                    {new Date(s.updatedAt).toLocaleDateString("zh-CN")} · {s.turns.filter(t => t.role === "user").length}轮对话
                  </div>
                </div>
                <button
                  onClick={(e) => deleteSession(s.id, e)}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)", fontSize: 16, padding: "4px 6px", lineHeight: 1, flexShrink: 0, borderRadius: 4 }}
                  title="删除"
                >✕</button>
              </div>
            ))
          }
        </div>
      </div>

      {/* Header */}
      <div className="market-header">
        <span className="market-title"><span className="market-title-icon">✦</span> AI 写作 / 问答</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <button className="tbtn" onClick={() => setHistoryOpen(o => !o)}>
            ≡ 历史{sessions.length > 0 ? ` (${sessions.length})` : ""}
          </button>
          <button className="tbtn" onClick={startNew} disabled={streaming || turns.length === 0}>＋ 新对话</button>
        </div>
      </div>

      {/* Chat body + input (full width, flex column) */}
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 12, overflow: "hidden" }}>
        <div ref={bodyRef} className="asst-body">
          {turns.length === 0 && (
            <div className="market-empty">
              <div className="market-empty-icon">✦</div>
              <div className="market-empty-title">问我任何问题，或让我帮你写文档/文案</div>
              <div className="market-empty-hint">纯文本 AI（全局兜底 / DeepSeek）· 支持 Markdown 文档输出</div>
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className={"asst-msg " + t.role}>
              <div className="asst-role">{t.role === "user" ? "我" : "AI"}</div>
              <div className="asst-content">
                {t.role === "assistant"
                  ? (t.content ? <MarkdownReport text={t.content} /> : <span className="cursor-blink">▋</span>)
                  : <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.7 }}>{t.content}</div>}
              </div>
            </div>
          ))}
        </div>

        {err && <div className="market-error" style={{ flexShrink: 0 }}>{err}</div>}

        <div className="market-input-row">
          <textarea
            className="market-query-input"
            style={{ resize: "none", height: 44, paddingTop: 10 }}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}
            placeholder="输入问题或写作要求，Enter 发送（Shift+Enter 换行）"
            disabled={streaming}
          />
          {streaming
            ? <button className="market-btn market-btn-stop" onClick={stop}>停止</button>
            : <button className="market-btn market-btn-submit" onClick={send} disabled={!input.trim()}>发送</button>}
        </div>
      </div>
    </div>
  );
}
