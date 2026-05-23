import type { Project, ProjectSession } from "../../../api/projects";

type Props = {
  project: Project | null;
  session: ProjectSession | null;
  onOpenSidebar: () => void;
  onNewSession: () => void;
  onOpenPalette?: () => void;
  /** Called with the gear button's bounding rect so the popover can be
   * positioned right under the icon. */
  onOpenQuickSettings?: (rect: DOMRect) => void;
};

/**
 * Workspace top bar: hamburger (mobile only) | breadcrumb | actions.
 *
 * Breadcrumb walks Project > Session title with sensible empty states.
 * The hamburger is hidden on desktop via CSS (.ws-mobile-only) — the
 * sidebar is always-visible there.
 *
 * Actions on the right: ⌘K search trigger, settings cog (Phase D),
 * "新建" CTA.
 */
export default function TopBar({
  project, session,
  onOpenSidebar, onNewSession,
  onOpenPalette, onOpenQuickSettings,
}: Props) {
  return (
    <div className="ws-topbar">
      <button
        className="ws-topbar-btn ws-mobile-only"
        onClick={onOpenSidebar}
        title="打开项目列表"
        aria-label="打开项目列表"
      >
        ☰
      </button>
      <div className="ws-crumbs">
        <span className="ws-crumb-project" title={project?.path || ""}>
          {project ? project.name : <span className="ws-crumb-faint">未选择项目</span>}
        </span>
        {session && (
          <>
            <span className="ws-crumb-sep">/</span>
            <span className={"ws-src-chip src-" + session.source}>{session.source}</span>
            <span className="ws-crumb-session" title={session.title}>{session.title}</span>
          </>
        )}
      </div>
      <div className="ws-topbar-actions">
        {onOpenPalette && (
          <button
            className="ws-topbar-btn ws-cmdk-trigger"
            onClick={onOpenPalette}
            title="命令面板（⌘K / Ctrl+K）"
            aria-label="打开命令面板"
          >
            <span style={{ marginRight: 6 }}>⌕</span>
            <kbd className="ws-kbd ws-desktop-only">⌘K</kbd>
          </button>
        )}
        {onOpenQuickSettings && (
          <button
            className="ws-topbar-btn"
            onClick={(e) => onOpenQuickSettings((e.currentTarget as HTMLElement).getBoundingClientRect())}
            title="快捷设置"
            aria-label="快捷设置"
          >
            ⚙
          </button>
        )}
        <button
          className="tbtn tbtn-acc"
          onClick={onNewSession}
          title="在当前项目下新建会话"
        >
          + 新建
        </button>
      </div>
    </div>
  );
}
