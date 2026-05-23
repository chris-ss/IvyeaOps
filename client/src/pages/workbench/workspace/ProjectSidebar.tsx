import type { Project, ProjectSession } from "../../../api/projects";

type Props = {
  projects: Project[];
  loading: boolean;
  selectedProjectId: string | null;
  selectedSessionId: string | null;
  expandedIds: Set<string>;
  sessionsByProject: Record<string, ProjectSession[] | undefined>;
  loadingSessionsFor: Record<string, boolean>;
  onToggleExpand: (projectId: string) => void;
  onSelectSession: (projectId: string, session: ProjectSession) => void;
  /** Delete a hub session. Caller handles confirmation + refresh + clearing
   * the workspace selection if needed. External (claude/codex) sessions
   * intentionally cannot be deleted here — they belong to the respective
   * upstream tool. */
  onDeleteSession?: (projectId: string, session: ProjectSession) => void;
  onRefresh: () => void;
  onClose?: () => void;
};

/**
 * Two-level sidebar à la claudecodeui:
 *   – row 1: project (click chevron to expand, click name to expand-and-pick)
 *   – row 2..N: sessions belonging to that project, indented
 *
 * Sources (hub / claude / codex) are color-coded chips on each session row
 * so the user knows whether the entry is interactive (hub) or read-only
 * jsonl (claude/codex). Selection state lives in the parent so URL routing
 * stays the source of truth.
 */
export default function ProjectSidebar({
  projects, loading,
  selectedProjectId, selectedSessionId,
  expandedIds, sessionsByProject, loadingSessionsFor,
  onToggleExpand, onSelectSession, onDeleteSession, onRefresh, onClose,
}: Props) {
  return (
    <div className="ws-sidebar">
      <div className="ws-sidebar-head">
        <span className="ws-sidebar-title">项目</span>
        <button className="ws-icon-btn" onClick={onRefresh} title="刷新项目列表">↻</button>
        {onClose && (
          <button className="ws-icon-btn ws-sidebar-close" onClick={onClose} title="关闭" aria-label="关闭侧边栏">✕</button>
        )}
      </div>
      <div className="ws-sidebar-body">
        {loading && projects.length === 0 ? (
          <div className="ws-sidebar-empty">加载中…</div>
        ) : projects.length === 0 ? (
          <div className="ws-sidebar-empty">没有发现项目</div>
        ) : projects.map((p) => (
          <ProjectRow
            key={p.id}
            project={p}
            expanded={expandedIds.has(p.id)}
            isCurrent={selectedProjectId === p.id}
            sessions={sessionsByProject[p.id]}
            loadingSessions={!!loadingSessionsFor[p.id]}
            selectedSessionId={selectedProjectId === p.id ? selectedSessionId : null}
            onToggle={() => onToggleExpand(p.id)}
            onSelectSession={(s) => onSelectSession(p.id, s)}
            onDeleteSession={onDeleteSession ? (s) => onDeleteSession(p.id, s) : undefined}
          />
        ))}
      </div>
    </div>
  );
}

function ProjectRow({
  project, expanded, isCurrent,
  sessions, loadingSessions,
  selectedSessionId,
  onToggle, onSelectSession, onDeleteSession,
}: {
  project: Project;
  expanded: boolean;
  isCurrent: boolean;
  sessions: ProjectSession[] | undefined;
  loadingSessions: boolean;
  selectedSessionId: string | null;
  onToggle: () => void;
  onSelectSession: (s: ProjectSession) => void;
  onDeleteSession?: (s: ProjectSession) => void;
}) {
  const isUnknown = project.path === "(unknown)";
  // Folder glyph for normal projects; a light dotted-circle for the synthetic
  // "(unknown)" bucket that groups hub sessions with no workdir. Avoids the
  // jarring ASCII "?" we had before.
  const icon = isUnknown ? "◌" : "📁";
  return (
    <div className="ws-project">
      <div
        className={"ws-project-row" + (isCurrent ? " current" : "") + (isUnknown ? " unknown" : "")}
        onClick={onToggle}
      >
        <span className="ws-chevron" data-expanded={expanded ? "1" : "0"}>▸</span>
        <span className="ws-project-icon">{icon}</span>
        <span className="ws-project-name" title={project.path}>
          {isUnknown ? "未关联项目" : project.name}
        </span>
        <span className="ws-project-count">{project.session_count}</span>
      </div>
      {expanded && (
        <div className="ws-session-list">
          {loadingSessions && !sessions ? (
            <div className="ws-session-empty">加载中…</div>
          ) : !sessions || sessions.length === 0 ? (
            <div className="ws-session-empty">空</div>
          ) : sessions.map((s) => (
            <SessionRow
              key={`${s.source}-${s.id}`}
              session={s}
              selected={selectedSessionId === s.id}
              onSelect={() => onSelectSession(s)}
              onDelete={onDeleteSession ? () => onDeleteSession(s) : undefined}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SessionRow({ session, selected, onSelect, onDelete }: {
  session: ProjectSession;
  selected: boolean;
  onSelect: () => void;
  /** Only set for hub sessions — external claude/codex jsonl rows can't be
   * deleted from here (their files belong to the upstream tool). */
  onDelete?: () => void;
}) {
  const srcShort = session.source === "hub" ? "HUB"
    : session.source === "claude" ? "CC"
    : session.source === "codex" ? "CX"
    : String(session.source).toUpperCase().slice(0, 3);
  const canDelete = !!onDelete && session.source === "hub";
  return (
    <div className={"ws-session-row" + (selected ? " selected" : "")} onClick={onSelect}>
      <span className={"ws-session-src src-" + session.source}>{srcShort}</span>
      <span className="ws-session-title" title={session.title}>{session.title}</span>
      <span className="ws-session-time" title={session.last_active_iso}>
        {relativeTime(session.last_active)}
      </span>
      {canDelete && (
        <button
          className="ws-session-del"
          onClick={(e) => { e.stopPropagation(); onDelete?.(); }}
          title="删除会话"
          aria-label="删除会话"
        >🗑</button>
      )}
    </div>
  );
}

function relativeTime(unix: number): string {
  if (!unix) return "";
  const diff = Date.now() - unix * 1000;
  const m = Math.floor(diff / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return m + "m";
  const h = Math.floor(m / 60);
  if (h < 24) return h + "h";
  const d = Math.floor(h / 24);
  if (d < 30) return d + "d";
  return Math.floor(d / 30) + "mo";
}

