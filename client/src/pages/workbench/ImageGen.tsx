import { useEffect, useRef, useState, type MouseEvent } from "react";
import { submitImage, imageStatus } from "../../api/assistant";
import SheetSelect from "../../components/SheetSelect";

const SIZES = ["1024x1024", "1024x1536", "1536x1024"];
const SESSIONS_KEY = "ivyea-ops-imagegen-sessions";
const MAX_SESSIONS = 20;

interface ImageTurn {
  id: string;
  prompt: string;
  images: string[];
  loading?: boolean;
  progress?: number;
  error?: string;
}

interface ImageSession {
  id: string;
  title: string;
  turns: ImageTurn[];
  size: string;
  n: number;
  updatedAt: number;
}

function loadSessions(): ImageSession[] {
  try { const r = localStorage.getItem(SESSIONS_KEY); if (r) return JSON.parse(r); } catch {}
  return [];
}

function saveSessions(sessions: ImageSession[]) {
  try { localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.slice(0, MAX_SESSIONS))); } catch {}
}

function sessionTitle(turns: ImageTurn[]): string {
  const first = turns[0];
  if (!first) return "新建图";
  return first.prompt.length > 24 ? first.prompt.slice(0, 24) + "…" : first.prompt;
}

export default function ImageGen() {
  const [sessions, setSessions] = useState<ImageSession[]>(loadSessions);
  const [currentId, setCurrentId] = useState<string>(() => Date.now().toString());
  const [turns, setTurns] = useState<ImageTurn[]>([]);
  const [size, setSize] = useState(SIZES[0]);
  const [n, setN] = useState(1);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const timerRef = useRef<number | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => () => { if (timerRef.current) clearInterval(timerRef.current); }, []);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [turns]);

  // Auto-save session whenever turns change
  useEffect(() => {
    const completed = turns.filter(t => !t.loading && t.images.length > 0);
    if (completed.length === 0) return;
    const session: ImageSession = { id: currentId, title: sessionTitle(turns), turns, size, n, updatedAt: Date.now() };
    setSessions(prev => {
      const idx = prev.findIndex(s => s.id === currentId);
      const next = idx >= 0
        ? [...prev.slice(0, idx), session, ...prev.slice(idx + 1)]
        : [session, ...prev];
      saveSessions(next);
      return next;
    });
  }, [turns, currentId, size, n]);

  const run = async () => {
    const text = input.trim();
    if (!text || loading) return;
    const turnId = Date.now().toString();
    const newTurn: ImageTurn = { id: turnId, prompt: text, images: [], loading: true, progress: 0 };
    setTurns(prev => [...prev, newTurn]);
    setInput("");
    setLoading(true);
    try {
      const taskId = await submitImage(text, size, n);
      const started = Date.now();
      timerRef.current = window.setInterval(async () => {
        try {
          const s = await imageStatus(taskId);
          setTurns(prev => {
            const next = [...prev];
            const idx = next.findIndex(t => t.id === turnId);
            if (idx < 0) return prev;
            next[idx] = { ...next[idx], progress: s.progress || 0 };
            return next;
          });
          if (s.status === "completed") {
            clearInterval(timerRef.current!); timerRef.current = null;
            setTurns(prev => {
              const next = [...prev];
              const idx = next.findIndex(t => t.id === turnId);
              if (idx < 0) return prev;
              next[idx] = { ...next[idx], images: s.images, loading: false, progress: undefined };
              return next;
            });
            setLoading(false);
          } else if (s.status === "failed" || s.error) {
            clearInterval(timerRef.current!); timerRef.current = null;
            setTurns(prev => {
              const next = [...prev];
              const idx = next.findIndex(t => t.id === turnId);
              if (idx < 0) return prev;
              next[idx] = { ...next[idx], error: s.error || "生图失败", loading: false };
              return next;
            });
            setLoading(false);
          } else if (Date.now() - started > 180000) {
            clearInterval(timerRef.current!); timerRef.current = null;
            setTurns(prev => {
              const next = [...prev];
              const idx = next.findIndex(t => t.id === turnId);
              if (idx < 0) return prev;
              next[idx] = { ...next[idx], error: "生图超时（>3分钟）", loading: false };
              return next;
            });
            setLoading(false);
          }
        } catch (e: any) {
          clearInterval(timerRef.current!); timerRef.current = null;
          setTurns(prev => {
            const next = [...prev];
            const idx = next.findIndex(t => t.id === turnId);
            if (idx < 0) return prev;
            next[idx] = { ...next[idx], error: e?.message || "查询失败", loading: false };
            return next;
          });
          setLoading(false);
        }
      }, 4000);
    } catch (e: any) {
      setTurns(prev => {
        const next = [...prev];
        const idx = next.findIndex(t => t.id === turnId);
        if (idx < 0) return prev;
        next[idx] = { ...next[idx], error: e?.message || "提交失败", loading: false };
        return next;
      });
      setLoading(false);
    }
  };

  const startNew = () => {
    if (loading) return;
    setCurrentId(Date.now().toString());
    setTurns([]);
    setInput("");
    setHistoryOpen(false);
  };

  const loadSession = (s: ImageSession) => {
    if (loading) return;
    setCurrentId(s.id);
    setTurns(s.turns);
    setSize(s.size);
    setN(s.n);
    setInput("");
    setHistoryOpen(false);
  };

  const deleteSession = (id: string, e: MouseEvent) => {
    e.stopPropagation();
    setSessions(prev => {
      const next = prev.filter(s => s.id !== id);
      saveSessions(next);
      return next;
    });
    if (id === currentId) startNew();
  };

  return (
    <div className="market-page imggen-page">
      {/* Bottom sheet backdrop */}
      {historyOpen && (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 897, background: "rgba(0,0,0,.5)" }}
          onClick={() => setHistoryOpen(false)}
        />
      )}

      {/* Bottom sheet */}
      <div style={{
        position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 898,
        maxHeight: "62vh", background: "var(--bg1)",
        borderRadius: "16px 16px 0 0",
        display: "flex", flexDirection: "column",
        boxShadow: "0 -4px 32px rgba(0,0,0,.4)",
        transform: historyOpen ? "translateY(0)" : "translateY(110%)",
        transition: "transform .25s cubic-bezier(.4,0,.2,1)",
      }}>
        <div style={{ display: "flex", justifyContent: "center", padding: "10px 0 4px", flexShrink: 0 }}>
          <div style={{ width: 36, height: 4, borderRadius: 2, background: "var(--b2)" }} />
        </div>
        <div style={{ display: "flex", alignItems: "center", padding: "2px 16px 10px", flexShrink: 0, borderBottom: "1px solid var(--b)" }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--t)", flex: 1 }}>生成历史</span>
          <button className="tbtn" onClick={startNew} disabled={loading} style={{ marginRight: 8 }}>＋ 新建</button>
          <button
            onClick={() => setHistoryOpen(false)}
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)", fontSize: 18, padding: "0 2px", lineHeight: 1 }}
          >✕</button>
        </div>
        <div style={{ overflowY: "auto", flex: 1 }}>
          {sessions.length === 0
            ? <div style={{ padding: "28px 16px", fontSize: 13, color: "var(--t3)", textAlign: "center" }}>暂无历史记录</div>
            : sessions.map(s => {
              const allImgs = s.turns.flatMap(t => t.images).slice(0, 4);
              const isActive = s.id === currentId;
              return (
                <div
                  key={s.id}
                  onClick={() => loadSession(s)}
                  style={{
                    padding: "10px 16px", cursor: "pointer", borderBottom: "1px solid var(--b)",
                    background: isActive ? "color-mix(in srgb, var(--acc) 10%, transparent)" : undefined,
                    display: "flex", alignItems: "center", gap: 12, transition: "background .12s",
                  }}
                  onMouseEnter={e => { if (!isActive) (e.currentTarget as HTMLDivElement).style.background = "var(--bg3)"; }}
                  onMouseLeave={e => { if (!isActive) (e.currentTarget as HTMLDivElement).style.background = ""; }}
                >
                  {/* Thumbnail strip */}
                  <div style={{ display: "flex", gap: 3, flexShrink: 0 }}>
                    {allImgs.length > 0
                      ? allImgs.map((u, i) => (
                        <img key={i} src={u} alt="" style={{ width: 40, height: 40, borderRadius: 5, objectFit: "cover", background: "var(--bg3)" }} />
                      ))
                      : <div style={{ width: 40, height: 40, borderRadius: 5, background: "var(--bg3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, color: "var(--t3)" }}>▦</div>
                    }
                  </div>
                  <div style={{ flex: 1, overflow: "hidden" }}>
                    <div style={{
                      fontSize: 13, fontWeight: isActive ? 600 : 400,
                      color: isActive ? "var(--acc)" : "var(--t)",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>{s.title}</div>
                    <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>
                      {new Date(s.updatedAt).toLocaleDateString("zh-CN")} · {s.turns.length}轮 · {s.size}
                    </div>
                  </div>
                  <button
                    onClick={(e) => deleteSession(s.id, e)}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)", fontSize: 16, padding: "4px 6px", lineHeight: 1, flexShrink: 0, borderRadius: 4 }}
                    title="删除"
                  >✕</button>
                </div>
              );
            })
          }
        </div>
      </div>

      {/* Header */}
      <div className="market-header">
        <span className="market-title"><span className="market-title-icon">▦</span> AI 生图</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <button className="tbtn" onClick={() => setHistoryOpen(o => !o)}>
            ≡ 历史{sessions.length > 0 ? ` (${sessions.length})` : ""}
          </button>
          <button className="tbtn" onClick={startNew} disabled={loading || turns.length === 0}>＋ 新建</button>
        </div>
      </div>

      {/* Conversation body */}
      <div ref={bodyRef} className="imggen-body">
        {turns.length === 0 && (
          <div className="market-empty">
            <div className="market-empty-icon">▦</div>
            <div className="market-empty-title">输入提示词，用 AI 生成图片</div>
            <div className="market-empty-hint">Apimart gpt-image-2 · 英文提示词效果更佳 · 可连续追加修改要求</div>
          </div>
        )}
        {turns.map((turn) => (
          <div key={turn.id} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {/* User prompt */}
            <div style={{ display: "flex", gap: 10, alignItems: "flex-start", flexDirection: "row-reverse" }}>
              <div style={{
                width: 30, height: 30, borderRadius: 8, flexShrink: 0,
                background: "color-mix(in srgb, var(--acc) 18%, transparent)",
                color: "var(--acc)", display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 11, fontWeight: 600, border: "1px solid transparent",
              }}>我</div>
              <div style={{
                background: "color-mix(in srgb, var(--acc) 8%, transparent)",
                border: "1px solid var(--b)", borderRadius: 10, padding: "8px 12px",
                fontSize: 13, color: "var(--t)", lineHeight: 1.6, maxWidth: "80%",
              }}>{turn.prompt}</div>
            </div>
            {/* Result */}
            {turn.loading ? (
              <div style={{ marginLeft: 40 }} aria-busy="true" aria-live="polite">
                <div className="pulse-loading" style={{ marginBottom: 8 }}>
                  <span className="pulse-spin">◌</span>
                  生成中（约 1 分钟）{turn.progress ? `… ${turn.progress}%` : "…"}
                </div>
                <div className="imggen-grid">
                  {Array.from({ length: Math.max(1, n) }).map((_, i) => (
                    <div key={i} className="imggen-card">
                      <div className="skeleton" style={{ width: "100%", height: 180, borderRadius: 6 }} />
                    </div>
                  ))}
                </div>
              </div>
            ) : turn.error ? (
              <div className="market-error" style={{ marginLeft: 40 }}>{turn.error}</div>
            ) : (
              <div className="imggen-grid wb-enter" style={{ marginLeft: 40 }}>
                {turn.images.map((u, i) => (
                  <div key={i} className="imggen-card">
                    <img src={u} alt="" />
                    <a className="tbtn" href={u} target="_blank" rel="noreferrer">下载 / 查看</a>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Input area — stays at bottom */}
      <div className="market-input-row" style={{ flexWrap: "wrap" }}>
        <textarea
          className="market-query-input"
          style={{ resize: "none", height: 44, paddingTop: 10 }}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(); } }}
          placeholder={turns.length > 0 ? "继续描述修改要求，Enter 发送（Shift+Enter 换行）" : "描述你想要的图片，英文效果更佳，Enter 发送"}
          disabled={loading}
        />
        <SheetSelect
          className="market-query-input"
          style={{ flex: "0 0 auto", minWidth: 110 }}
          value={size}
          onChange={setSize}
          disabled={loading}
          title="图片尺寸"
          options={SIZES}
        />
        <SheetSelect
          className="market-query-input"
          style={{ flex: "0 0 auto", minWidth: 60 }}
          value={String(n)}
          onChange={v => setN(Number(v))}
          disabled={loading}
          title="生成数量"
          options={[1, 2, 3, 4].map(x => ({ value: String(x), label: `${x} 张` }))}
        />
        <button className="market-btn market-btn-submit" onClick={run} disabled={loading || !input.trim()}>
          {loading ? <><span className="spin" style={{ marginRight: 6 }} />生成中…</> : "生成"}
        </button>
      </div>
    </div>
  );
}
