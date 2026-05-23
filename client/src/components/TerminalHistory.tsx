import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";

interface Session {
  id: number;
  ts: string;
  title: string;
  source: string;
  size: number;
}

interface SearchHit extends Session {
  snippet: string;
}

export default function TerminalHistory({ onClose }: { onClose: () => void }) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [viewing, setViewing] = useState<{ id: number; title: string; content: string } | null>(null);
  const [bashLines, setBashLines] = useState<string[] | null>(null);
  const [tab, setTab] = useState<"sessions" | "bash">("sessions");
  const [saving, setSaving] = useState(false);

  // Search state — when `query` is non-empty we render `searchHits` instead
  // of the full session list.
  const [query, setQuery] = useState("");
  const [searchHits, setSearchHits] = useState<SearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const debounceRef = useRef<number | null>(null);

  useEffect(() => {
    loadSessions();
  }, []);

  // Debounced server-side search whenever the query changes.
  useEffect(() => {
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current);
    }
    const trimmed = query.trim();
    if (!trimmed) {
      setSearchHits(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    debounceRef.current = window.setTimeout(async () => {
      try {
        const { data } = await api.get("/terminal/search", { params: { q: trimmed, limit: 100 } });
        setSearchHits(data.sessions || []);
      } catch {
        setSearchHits([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => {
      if (debounceRef.current !== null) {
        window.clearTimeout(debounceRef.current);
      }
    };
  }, [query]);

  async function loadSessions() {
    try {
      const { data } = await api.get("/terminal/sessions");
      setSessions(data.sessions || []);
    } catch {}
  }

  async function loadBash() {
    if (bashLines) return;
    try {
      const { data } = await api.get("/terminal/bash-history", { params: { lines: 200 } });
      setBashLines(data.lines || []);
    } catch {
      setBashLines([]);
    }
  }

  async function capture() {
    setSaving(true);
    try {
      const { data } = await api.post("/terminal/capture");
      if (data.ok) {
        await loadSessions();
        if (data.skipped) {
          // No-op: server says content unchanged, just refresh quietly.
        }
      } else {
        alert(data.error || "捕获失败");
      }
    } catch {
      alert("请求失败");
    }
    setSaving(false);
  }

  async function viewSession(s: { id: number }) {
    try {
      const { data } = await api.get(`/terminal/sessions/${s.id}`);
      setViewing({ id: data.id, title: data.title, content: data.content });
    } catch {}
  }

  async function deleteSession(id: number) {
    if (!confirm("确定删除此会话记录？")) return;
    try {
      await api.delete(`/terminal/sessions/${id}`);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (searchHits) {
        setSearchHits((prev) => (prev ? prev.filter((s) => s.id !== id) : prev));
      }
      if (viewing?.id === id) setViewing(null);
    } catch {}
  }

  // Highlight occurrences of the search query in a snippet, returning
  // an array of React nodes. Case-insensitive, all hits highlighted.
  const highlight = useMemo(() => {
    return (text: string, q: string) => {
      if (!q) return text;
      const lower = text.toLowerCase();
      const needle = q.toLowerCase();
      const parts: (string | { hit: string; key: number })[] = [];
      let i = 0;
      let key = 0;
      while (i < text.length) {
        const idx = lower.indexOf(needle, i);
        if (idx < 0) {
          parts.push(text.slice(i));
          break;
        }
        if (idx > i) parts.push(text.slice(i, idx));
        parts.push({ hit: text.slice(idx, idx + needle.length), key: key++ });
        i = idx + needle.length;
      }
      return parts.map((p, n) =>
        typeof p === "string" ? (
          <span key={`s${n}`}>{p}</span>
        ) : (
          <mark key={`h${p.key}`} className="th-mark">{p.hit}</mark>
        )
      );
    };
  }, []);

  if (viewing) {
    return (
      <div className="th-panel">
        <div className="th-header">
          <button className="tbtn" onClick={() => setViewing(null)}>← 返回</button>
          <span className="th-title">{viewing.title}</span>
        </div>
        <pre className="th-content">{viewing.content}</pre>
      </div>
    );
  }

  const showingSearch = tab === "sessions" && searchHits !== null;

  return (
    <div className="th-panel">
      <div className="th-header">
        <div className="th-tabs">
          <button
            className={"th-tab" + (tab === "sessions" ? " active" : "")}
            onClick={() => setTab("sessions")}
          >
            会话快照
          </button>
          <button
            className={"th-tab" + (tab === "bash" ? " active" : "")}
            onClick={() => { setTab("bash"); loadBash(); }}
          >
            命令历史
          </button>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {tab === "sessions" && (
            <button className="tbtn" onClick={capture} disabled={saving}>
              {saving ? "保存中…" : "📸 保存当前"}
            </button>
          )}
          <button className="tbtn" onClick={onClose}>✕</button>
        </div>
      </div>

      {tab === "sessions" && (
        <>
          <div className="th-search">
            <input
              className="th-search-input"
              placeholder="🔍 搜索会话内容（关键字、命令、错误信息…）"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {query && (
              <button
                className="th-search-clear"
                onClick={() => setQuery("")}
                title="清空"
              >
                ✕
              </button>
            )}
          </div>

          <div className="th-list">
            {showingSearch ? (
              <>
                {searching && <div className="th-empty">搜索中…</div>}
                {!searching && searchHits!.length === 0 && (
                  <div className="th-empty">没有命中"{query}"的会话。</div>
                )}
                {!searching && searchHits!.map((s) => (
                  <div key={s.id} className="th-item" onClick={() => viewSession(s)}>
                    <div className="th-item-info">
                      <span className="th-item-title">{s.title}</span>
                      <span className="th-item-snippet">
                        {highlight(s.snippet, query)}
                      </span>
                      <span className="th-item-meta">
                        {s.ts.replace("T", " ")} · {Math.round(s.size / 1024)}KB
                      </span>
                    </div>
                    <button
                      className="th-del"
                      onClick={(e) => { e.stopPropagation(); deleteSession(s.id); }}
                      title="删除"
                    >
                      🗑
                    </button>
                  </div>
                ))}
              </>
            ) : (
              <>
                {sessions.length === 0 && (
                  <div className="th-empty">暂无保存的会话。点击"保存当前"捕获终端内容。</div>
                )}
                {sessions.map((s) => (
                  <div key={s.id} className="th-item" onClick={() => viewSession(s)}>
                    <div className="th-item-info">
                      <span className="th-item-title">{s.title}</span>
                      <span className="th-item-meta">
                        {s.ts.replace("T", " ")} · {Math.round(s.size / 1024)}KB
                      </span>
                    </div>
                    <button
                      className="th-del"
                      onClick={(e) => { e.stopPropagation(); deleteSession(s.id); }}
                      title="删除"
                    >
                      🗑
                    </button>
                  </div>
                ))}
              </>
            )}
          </div>
        </>
      )}

      {tab === "bash" && (
        <pre className="th-content">
          {bashLines === null ? "加载中…" : bashLines.join("\n") || "无历史记录"}
        </pre>
      )}
    </div>
  );
}
