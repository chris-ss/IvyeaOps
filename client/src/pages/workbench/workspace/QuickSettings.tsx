import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getSession, updateSession, type AgentSession } from "../../../api/agents";
import { refreshProjects, type Project, type ProjectSession } from "../../../api/projects";

type Props = {
  open: boolean;
  onClose: () => void;
  /** Anchor element rect, used to position the popover near the gear icon. */
  anchorRect: DOMRect | null;
  project: Project | null;
  session: ProjectSession | null;
  onAfterRefresh: () => void;
};

/**
 * Lightweight popover triggered by the TopBar gear icon.
 *
 * Doesn't try to replace /hub-settings — only surfaces the few toggles
 * that are common during day-to-day use:
 *   – Current session's model (hub only) with inline switcher
 *   – Refresh project list
 *   – Link to full /hub-settings (deep link to the relevant section)
 */
export default function QuickSettings({
  open, onClose, anchorRect, project, session, onAfterRefresh,
}: Props) {
  const navigate = useNavigate();
  const ref = useRef<HTMLDivElement>(null);
  const [hubSession, setHubSession] = useState<AgentSession | null>(null);
  const [modelDraft, setModelDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Click-outside to close
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  // Load hub-session details (for the model switcher) only when relevant.
  useEffect(() => {
    if (!open || !session || session.source !== "hub") {
      setHubSession(null);
      return;
    }
    let alive = true;
    getSession(session.id)
      .then((s) => { if (alive) { setHubSession(s); setModelDraft(s.model || ""); } })
      .catch(() => { /* swallow — read-only fetch */ });
    return () => { alive = false; };
  }, [open, session]);

  if (!open) return null;

  const top = anchorRect ? Math.min(anchorRect.bottom + 6, window.innerHeight - 360) : 60;
  const right = anchorRect ? Math.max(8, window.innerWidth - anchorRect.right) : 8;
  const style = { top, right };

  const saveModel = async () => {
    if (!hubSession) return;
    const next = modelDraft.trim();
    if (!next || next === hubSession.model) return;
    setSaving(true);
    setErr(null);
    try {
      const updated = await updateSession(hubSession.id, { model: next });
      setHubSession(updated);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    try {
      await refreshProjects();
      onAfterRefresh();
    } catch { /* ignore */ }
    setRefreshing(false);
  };

  return (
    <div className="qs-popover" style={style} ref={ref}>
      <div className="qs-head">
        <span className="qs-title">快捷设置</span>
        <button className="qs-close" onClick={onClose} aria-label="关闭">✕</button>
      </div>

      {/* Current session model — only for hub sessions */}
      {session?.source === "hub" ? (
        <section className="qs-section">
          <div className="qs-section-title">当前会话 · 模型</div>
          {hubSession ? (
            <div className="qs-row">
              <input
                className="qs-input"
                value={modelDraft}
                onChange={(e) => setModelDraft(e.target.value)}
                placeholder={hubSession.model || "如 anthropic/claude-sonnet-4.6"}
                onKeyDown={(e) => { if (e.key === "Enter") void saveModel(); }}
              />
              <button
                className="tbtn tbtn-acc"
                onClick={saveModel}
                disabled={saving || !modelDraft.trim() || modelDraft.trim() === hubSession.model}
              >
                {saving ? "…" : "保存"}
              </button>
            </div>
          ) : (
            <div className="qs-loading">加载中…</div>
          )}
          {err && <div className="qs-err">⚠ {err}</div>}
        </section>
      ) : session ? (
        <section className="qs-section">
          <div className="qs-section-title">当前会话</div>
          <div className="qs-faint">
            外部 {session.source} 会话只读 · 切到「记录」tab 后点「↻ 继续会话」可创建可交互 hub 会话。
          </div>
        </section>
      ) : null}

      {/* Project list refresh */}
      <section className="qs-section">
        <div className="qs-section-title">项目数据源</div>
        <div className="qs-faint">
          每 30 秒服务端会缓存项目列表。本地刷新会重扫 <code>~/.claude/projects</code>、
          <code>~/.codex/sessions</code> 和 ops-hub 自身的 agent_sessions 表。
        </div>
        <button className="tbtn" onClick={refresh} disabled={refreshing} style={{ marginTop: 8 }}>
          {refreshing ? "刷新中…" : "↻ 重扫项目"}
        </button>
      </section>

      {/* Deep link to full settings */}
      <section className="qs-section">
        <div className="qs-section-title">全部设置</div>
        <div className="qs-links">
          <button
            className="qs-link"
            onClick={() => { onClose(); navigate("/hub-settings"); }}
          >→ 打开系统配置（API key / 提供商顺序 / 集成路径…）</button>
          <button
            className="qs-link"
            onClick={() => { onClose(); navigate("/skill/settings"); }}
          >→ Skill Studio 配置</button>
        </div>
      </section>

      {project && (
        <div className="qs-footer">
          <span className="qs-faint">{project.name}</span>
          {project.path !== "(unknown)" && (
            <span className="qs-faint" title={project.path}><code>{project.path}</code></span>
          )}
        </div>
      )}
    </div>
  );
}
