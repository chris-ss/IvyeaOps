import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useConfirm } from "../../../components/ConfirmDialog";
import { useWorkspaceData } from "./useWorkspaceData";
import ProjectSidebar from "./ProjectSidebar";
import MainTabs from "./MainTabs";
import TopBar from "./TopBar";
import MobileBottomNav from "./MobileBottomNav";
import CommandPalette from "./CommandPalette";
import QuickSettings from "./QuickSettings";
import MCPManager from "./MCPManager";
import Onboarding from "./Onboarding";
import AgentPicker from "../../../components/AgentPicker";
import { availableTabsFor, type TabKey } from "./tabs";
import type { ProjectSession } from "../../../api/projects";
import { createSession, deleteSession } from "../../../api/agents";

type Selection = {
  projectId: string | null;
  sessionId: string | null;
  sessionSource: string | null;  // "hub" | "claude" | "codex"
};

const SELECTION_KEY = "opshub-workspace-selection-v1";
const TAB_KEY = "opshub-workspace-active-tab";

/**
 * Workspace — top-level page that replaces AgentChat in Phase B.
 *
 * Composition:
 *   – ProjectSidebar (left)    list of projects, two-level expand, mobile drawer
 *   – TopBar         (top)     hamburger (mobile) + breadcrumb + actions
 *   – MainTabs       (center)  tab body (chat / shell / files / transcript / git)
 *   – MobileBottomNav (bottom) tab switcher on small screens
 *
 * Workspace owns the selection (projectId, sessionId) + activeTab; everything
 * else is a pure view that takes those as props. Selection persists to
 * localStorage so reloads restore context.
 */
export default function Workspace() {
  const confirm = useConfirm();
  const { projects, loadingProjects, refresh, getSessions, loadSessions, loadingSessionsFor } = useWorkspaceData();

  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [selection, setSelection] = useState<Selection>(() => {
    try {
      const raw = localStorage.getItem(SELECTION_KEY);
      if (raw) return JSON.parse(raw);
    } catch { /* ignore */ }
    return { projectId: null, sessionId: null, sessionSource: null };
  });
  const [activeTab, setActiveTab] = useState<TabKey | null>(() => {
    try {
      const saved = localStorage.getItem(TAB_KEY);
      if (saved) return saved as TabKey;
    } catch { /* ignore */ }
    return null;
  });
  const [sidebarOpen, setSidebarOpen] = useState(false);   // mobile drawer state
  const [pickerOpen, setPickerOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [qsAnchor, setQsAnchor] = useState<DOMRect | null>(null);   // null = closed
  const [mcpOpen, setMcpOpen] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(() => {
    try { return localStorage.getItem("opshub-workspace-onboarded") !== "1"; }
    catch { return false; }
  });
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  // Cross-page jump: Market (and other pages) can navigate here with a new
  // session pre-created and stored in sessionStorage.
  const jumpRef = useRef<{ sessionId: string; workdir: string | null } | null>(null);
  const jumpTriedRefreshRef = useRef(false);

  // Global ⌘K / Ctrl+K to toggle the command palette. Avoid swallowing
  // the shortcut when the user is typing inside an input/textarea that
  // already handles it (e.g. xterm has its own copy handler).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setCmdOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Persist selection so a reload restores where the user was.
  useEffect(() => {
    try { localStorage.setItem(SELECTION_KEY, JSON.stringify(selection)); } catch { /* ignore */ }
  }, [selection]);
  useEffect(() => {
    if (activeTab) {
      try { localStorage.setItem(TAB_KEY, activeTab); } catch { /* ignore */ }
    }
  }, [activeTab]);

  // Auto-expand the restored selection on first mount.
  useEffect(() => {
    if (selection.projectId && !expanded.has(selection.projectId)) {
      setExpanded((s) => new Set(s).add(selection.projectId!));
      void loadSessions(selection.projectId);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // On mount: read pending jump request from sessionStorage
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem("opshub-jump-session");
      if (raw) {
        sessionStorage.removeItem("opshub-jump-session");
        jumpRef.current = JSON.parse(raw);
      }
    } catch {}
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When projects update: process any pending jump
  useEffect(() => {
    if (!jumpRef.current || loadingProjects) return;
    const jump = jumpRef.current;
    const targetPath = jump.workdir || "(unknown)";
    const proj = projects.find((p) => p.path === targetPath)
      ?? projects.find((p) => p.path === "(unknown)");

    if (!proj) {
      if (!jumpTriedRefreshRef.current) {
        jumpTriedRefreshRef.current = true;
        void refresh();
      } else {
        jumpRef.current = null; // give up after one refresh
      }
      return;
    }

    jumpRef.current = null;
    jumpTriedRefreshRef.current = false;
    setExpanded((s) => new Set(s).add(proj.id));
    loadSessions(proj.id).then(() => {
      setSelection({ projectId: proj.id, sessionId: jump.sessionId, sessionSource: "hub" });
      setActiveTab("chat");
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects, loadingProjects]);

  const onToggleExpand = useCallback((projectId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(projectId)) next.delete(projectId);
      else {
        next.add(projectId);
        if (!getSessions(projectId)) void loadSessions(projectId);
      }
      return next;
    });
  }, [getSessions, loadSessions]);

  const onSelectSession = useCallback((projectId: string, s: ProjectSession) => {
    setSelection({ projectId, sessionId: s.id, sessionSource: s.source });
    setSidebarOpen(false);
  }, []);

  const onDeleteSession = useCallback(async (projectId: string, s: ProjectSession) => {
    // External jsonl rows are filtered out at the sidebar level — guard
    // here too as defense-in-depth.
    if (s.source !== "hub") return;
    const ok = await confirm({
      title: "删除会话",
      message: `确定删除会话「${s.title}」？\n该 hub 会话的全部消息也会一并删除（外部 jsonl 历史不受影响）。`,
      confirmText: "删除",
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteSession(s.id);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "删除失败");
      return;
    }
    // If the deleted row was the active selection, clear it.
    setSelection((prev) => {
      if (prev.sessionId === s.id) {
        return { projectId: prev.projectId, sessionId: null, sessionSource: null };
      }
      return prev;
    });
    // Reload sessions list under this project so the row disappears and
    // refresh project list for updated counts.
    await refresh();
    if (projectId) await loadSessions(projectId);
  }, [refresh, loadSessions]);

  const selectedProject = useMemo(
    () => (selection.projectId ? projects.find((p) => p.id === selection.projectId) || null : null),
    [projects, selection.projectId],
  );
  const selectedSession = useMemo(() => {
    if (!selection.projectId || !selection.sessionId) return null;
    const list = getSessions(selection.projectId);
    if (!list) return null;
    return list.find((s) => s.id === selection.sessionId) || null;
  }, [getSessions, selection.projectId, selection.sessionId]);

  const sessionsByProject = useMemo(() => {
    const out: Record<string, ProjectSession[] | undefined> = {};
    for (const p of projects) out[p.id] = getSessions(p.id);
    return out;
  }, [projects, getSessions]);

  // Tab availability changes with session type. Land on the first valid tab
  // whenever the current one becomes invalid (e.g. switching hub→claude
  // makes "chat" / "shell" disappear).
  const availableTabs = useMemo(
    () => availableTabsFor(selectedSession?.source),
    [selectedSession?.source],
  );
  useEffect(() => {
    if (!selectedSession) {
      setActiveTab(null);
      return;
    }
    if (!activeTab || !availableTabs.includes(activeTab)) {
      setActiveTab(availableTabs[0] ?? null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSession?.id, availableTabs]);

  const onCreate = useCallback(async (params: { agent_id: string; model: string; title: string; workdir?: string }) => {
    try {
      const s = await createSession({
        agent_id: params.agent_id,
        model: params.model,
        title: params.title,
        workdir: params.workdir,
      });
      setPickerOpen(false);
      await refresh();
      // The new session belongs to the project matching workdir; refresh
      // already invalidated projects. Switch selection to the new hub session.
      // Resolve its projectId via the path we just used.
      // Optimistic: scan refreshed projects on next render. For immediate UX,
      // we re-fetch projects list one more time and look up by workdir.
      const { listProjects } = await import("../../../api/projects");
      const fresh = await listProjects();
      const matched = fresh.find((p) => p.path === (params.workdir || "(unknown)"));
      const pid = matched?.id || selection.projectId;
      setSelection({ projectId: pid, sessionId: s.id, sessionSource: "hub" });
      if (pid) {
        setExpanded((set) => new Set(set).add(pid));
        void loadSessions(pid);
      }
      setActiveTab("chat");
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "创建失败");
    }
  }, [refresh, selection.projectId, loadSessions]);

  return (
    <div className={"ws-page" + (sidebarOpen ? " sidebar-open" : "")}>
      <div className="ws-sidebar-backdrop" onClick={() => setSidebarOpen(false)} />
      <ProjectSidebar
        projects={projects}
        loading={loadingProjects}
        selectedProjectId={selection.projectId}
        selectedSessionId={selection.sessionId}
        expandedIds={expanded}
        sessionsByProject={sessionsByProject}
        loadingSessionsFor={loadingSessionsFor}
        onToggleExpand={onToggleExpand}
        onSelectSession={onSelectSession}
        onDeleteSession={onDeleteSession}
        onRefresh={async () => {
          await refresh();
          await Promise.all([...expanded].map(loadSessions));
        }}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="ws-main">
        <TopBar
          project={selectedProject}
          session={selectedSession}
          onOpenSidebar={() => setSidebarOpen(true)}
          onNewSession={() => setPickerOpen(true)}
          onOpenPalette={() => setCmdOpen(true)}
          onOpenQuickSettings={(rect) => setQsAnchor(rect)}
        />
        <div className="ws-main-body">
          {selectedProject && selectedSession && activeTab ? (
            <MainTabs
              project={selectedProject}
              projectSession={selectedSession}
              activeTab={activeTab}
              onTabChange={setActiveTab}
              onResumed={async (newHubSessionId) => {
                await refresh();
                setSelection({
                  projectId: selection.projectId,
                  sessionId: newHubSessionId,
                  sessionSource: "hub",
                });
                if (selection.projectId) {
                  setExpanded((s) => new Set(s).add(selection.projectId!));
                  void loadSessions(selection.projectId);
                }
                setActiveTab("chat");
              }}
            />
          ) : (
            <div className="ws-main-empty">
              <div className="ws-main-empty-icon">◬</div>
              <div className="ws-main-empty-line">从左侧选择项目和会话开始</div>
              <div className="ws-main-empty-sub">
                共 {projects.length} 个项目可用 ·
                <button className="ws-link" onClick={() => setPickerOpen(true)}>新建会话</button>
              </div>
            </div>
          )}
        </div>
        <MobileBottomNav
          availableTabs={availableTabs}
          activeTab={activeTab}
          onTabChange={(t) => setActiveTab(t)}
          onOpenSidebar={() => setSidebarOpen(true)}
        />
      </div>
      {error && (
        <div className="ws-toast err">
          ⚠ {error}
          <button className="x-btn" onClick={() => setError(null)} aria-label="关闭">✕</button>
        </div>
      )}
      <AgentPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onConfirm={onCreate}
      />
      <CommandPalette
        open={cmdOpen}
        onClose={() => setCmdOpen(false)}
        projects={projects}
        sessionsByProject={sessionsByProject}
        currentProjectId={selection.projectId}
        availableTabs={availableTabs}
        onSelectProject={(pid) => {
          if (!expanded.has(pid)) {
            setExpanded((s) => new Set(s).add(pid));
            void loadSessions(pid);
          }
          setSelection({ projectId: pid, sessionId: null, sessionSource: null });
        }}
        onSelectSession={(pid, s) => onSelectSession(pid, s)}
        onSwitchTab={(t) => setActiveTab(t)}
        onNewSession={() => setPickerOpen(true)}
        onRefresh={() => { void refresh(); }}
        onOpenSettings={() => navigate("/hub-settings")}
      />
      <QuickSettings
        open={qsAnchor !== null}
        onClose={() => setQsAnchor(null)}
        anchorRect={qsAnchor}
        project={selectedProject}
        session={selectedSession}
        onAfterRefresh={() => { void refresh(); }}
        onOpenMCP={() => { setQsAnchor(null); setMcpOpen(true); }}
      />
      <MCPManager open={mcpOpen} onClose={() => setMcpOpen(false)} />
      {showOnboarding && (
        <Onboarding
          onDone={() => {
            setShowOnboarding(false);
            // After onboarding, refresh once so any newly-applied
            // integration paths show up in the sidebar / health check.
            void refresh();
          }}
        />
      )}
    </div>
  );
}
