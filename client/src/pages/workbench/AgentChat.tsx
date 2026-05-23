import { useCallback, useEffect, useState } from "react";
import {
  AgentSession,
  branchSession,
  compactSession,
  createSession,
  deleteSession,
  getSession,
  listMessages,
  listSessions,
  stopSessionPty,
  updateSession,
} from "../../api/agents";
import AgentPicker from "../../components/AgentPicker";
import BranchTree from "../../components/BranchTree";
import ChatPane from "../../components/ChatPane";
import AgentShell from "./agent/shell/AgentShell";
import AgentFiles from "./agent/files/AgentFiles";
import { useConfirm } from "../../components/ConfirmDialog";

type ViewMode = "chat" | "cli" | "files";

// Top-level page for the multi-agent hub.
//
// Layout: three columns inside a single bordered shell, matching the rest
// of ops-hub (workbench.css design tokens, dark green-accent terminal look).
//   left:   session tree + new-session action
//   center: tabs (chat | cli) for the active session
//   right:  meta panel (agent / model / branch / compact actions)
//
// On medium screens the right panel folds away; on mobile only the centre
// pane stays visible.
export default function AgentChat() {
  const confirm = useConfirm();
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [current, setCurrent] = useState<AgentSession | null>(null);
  const [mode, setMode] = useState<ViewMode>("chat");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Drawer state — only meaningful when columns are collapsed by media query.
  // CSS gates the visual effect, so toggling these on desktop is a no-op.
  const [treeOpen, setTreeOpen] = useState(false);
  const [metaOpen, setMetaOpen] = useState(false);

  const closeDrawers = useCallback(() => {
    setTreeOpen(false);
    setMetaOpen(false);
  }, []);

  const refreshList = useCallback(async () => {
    try {
      const list = await listSessions({ archived: showArchived });
      setSessions(list);
    } catch (e: any) {
      setError(e?.message || "加载会话列表失败");
    }
  }, [showArchived]);

  const refreshCurrent = useCallback(async () => {
    if (!currentId) {
      setCurrent(null);
      return;
    }
    try {
      const s = await getSession(currentId);
      setCurrent(s);
    } catch (e: any) {
      setError(e?.message || "加载会话失败");
      setCurrent(null);
    }
  }, [currentId]);

  useEffect(() => {
    refreshList();
  }, [refreshList]);

  useEffect(() => {
    refreshCurrent();
  }, [refreshCurrent]);

  // Periodically refresh the session list so live/dormant indicators stay
  // current without forcing the user to click around.
  useEffect(() => {
    const t = setInterval(refreshList, 8000);
    return () => clearInterval(t);
  }, [refreshList]);

  const onCreate = async (params: { agent_id: string; model: string; title: string; workdir?: string }) => {
    try {
      const s = await createSession({
        agent_id: params.agent_id,
        model: params.model,
        title: params.title,
        workdir: params.workdir,
      });
      setPickerOpen(false);
      await refreshList();
      setCurrentId(s.id);
      setMode("chat");
      closeDrawers();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "创建失败");
    }
  };

  const onCompact = async () => {
    if (!current || busy) return;
    setBusy(true);
    setError(null);
    try {
      await compactSession(current.id);
      await refreshCurrent();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "压缩失败");
    } finally {
      setBusy(false);
    }
  };

  const onBranch = async () => {
    if (!current) return;
    let anchor = 0;
    try {
      const r = await listMessages(current.id, { includeCli: true });
      anchor = r.messages[r.messages.length - 1]?.seq ?? 0;
    } catch {
      // ignore
    }
    if (anchor < 1) {
      setError("还没有消息可作为分支锚点");
      return;
    }
    try {
      const newSess = await branchSession(current.id, { anchor_seq: anchor });
      await refreshList();
      setCurrentId(newSess.id);
      setMode("chat");
      closeDrawers();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "分支失败");
    }
  };

  const onArchive = async () => {
    if (!current) return;
    try {
      await updateSession(current.id, { archived: !current.archived });
      await refreshList();
      await refreshCurrent();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "操作失败");
    }
  };

  const onDelete = async () => {
    if (!current) return;
    const ok = await confirm({
      title: "删除会话",
      message: `确定删除会话「${current.title}」？\n（有分支会被拒绝）`,
      confirmText: "删除",
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteSession(current.id);
      setCurrentId(null);
      await refreshList();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "删除失败");
    }
  };

  const onStopPty = async () => {
    if (!current) return;
    try {
      await stopSessionPty(current.id);
      await refreshCurrent();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "操作失败");
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
      {/* The page-level breadcrumb that used to live here ("/ 智能体会话") was
          removed because MainLayout's topbar already shows the same label
          ("~/智能体会话"). Keeping both wasted ~28px of vertical space and
          read as duplicate noise on mobile. */}

      <div
        className={
          "agent-hub" +
          (treeOpen ? " show-tree" : "") +
          (metaOpen ? " show-meta" : "")
        }
        style={{ flex: 1, minHeight: 0 }}
      >
        {/* Backdrop for the mobile drawers — only visible via CSS when a
            drawer is actually open (.show-tree / .show-meta). */}
        <div className="agent-hub-backdrop" onClick={closeDrawers} />

        {/* LEFT: session tree */}
        <div className="agent-hub-col col-tree">
          <div className="agent-hub-head">
            <span className="h-title">会话列表</span>
            <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 9, color: "var(--t3)", cursor: "pointer", fontFamily: "var(--font)", flexShrink: 0 }}>
              <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} style={{ accentColor: "var(--acc)", width: 11, height: 11 }} />
              已归档
            </label>
            <button className="btn-acc" onClick={() => setPickerOpen(true)} title="新建会话">
              + 新建
            </button>
          </div>
          <div className="agent-hub-body">
            <BranchTree
              sessions={sessions}
              currentId={currentId}
              onSelect={(id) => {
                setCurrentId(id);
                // Close the tree drawer on mobile after picking. On desktop
                // this state is ignored by CSS so it's a harmless write.
                setTreeOpen(false);
              }}
            />
          </div>
        </div>

        {/* CENTER: active session — single merged header bar holds the
            drawer toggles, the title, and the chat/cli tabs. Always
            rendered (even with no current session) so the menu stays
            reachable on mobile. */}
        <div className="agent-hub-col col-main">
          <div className="sess-head">
            {/* Top inner row: drawer toggle | live dot | title | info toggle.
                On desktop the toggles are hidden via CSS; on mobile they
                replace what used to be a separate .mobile-bar. */}
            <div className="sh-top">
              <button
                className="drawer-btn drawer-btn-tree"
                onClick={() => setTreeOpen((v) => !v)}
                aria-label="会话列表"
                title="会话列表"
              >
                ☰
              </button>
              <span style={{ color: current?.live ? "var(--acc)" : "var(--t3)", fontSize: 9, flexShrink: 0 }}>
                ●
              </span>
              {current ? (
                <input
                  className="st-input"
                  value={current.title}
                  onChange={(e) => setCurrent({ ...current, title: e.target.value })}
                  onBlur={async () => {
                    if (!current) return;
                    try {
                      await updateSession(current.id, { title: current.title });
                      refreshList();
                    } catch {
                      // ignore
                    }
                  }}
                  placeholder="会话标题"
                />
              ) : (
                <span className="st-input" style={{ color: "var(--t3)", display: "flex", alignItems: "center" }}>
                  选择或新建会话
                </span>
              )}
              {current && (
                <button
                  className="drawer-btn drawer-btn-meta"
                  onClick={() => setMetaOpen((v) => !v)}
                  aria-label="会话信息"
                  title="会话信息"
                >
                  ⓘ
                </button>
              )}
            </div>
            {/* Tabs row: only when a session is active. On desktop CSS
                puts this inline with sh-top; on mobile it wraps to its
                own row so the title gets the full width. */}
            {current && (
              <div className="tabs sh-tabs" style={{ margin: 0, border: "none", gap: 0 }}>
                <button
                  className={"tab" + (mode === "chat" ? " active" : "")}
                  onClick={() => setMode("chat")}
                >
                  聊天
                </button>
                <button
                  className={"tab" + (mode === "cli" ? " active" : "")}
                  onClick={() => setMode("cli")}
                >
                  终端
                </button>
                <button
                  className={"tab" + (mode === "files" ? " active" : "")}
                  onClick={() => setMode("files")}
                >
                  文件
                </button>
              </div>
            )}
          </div>

          {current ? (
            <>
              <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
                {mode === "chat" ? <ChatPane session={current} /> : mode === "cli" ? <AgentShell session={current} /> : <AgentFiles initialPath={current.workdir || "/root"} />}
              </div>
              {error && (
                <div className="inline-err">
                  <span>⚠ {error}</span>
                  <button className="x-btn" onClick={() => setError(null)} aria-label="关闭">
                    ✕
                  </button>
                </div>
              )}
            </>
          ) : (
            <div className="empty-state">
              <div className="es-icon">🍃</div>
              <div className="es-line es-desktop">请从左侧选择会话</div>
              <div className="es-line es-mobile">点击左上 ☰ 选择会话</div>
              <div style={{ fontSize: 10, color: "var(--t3)", maxWidth: 240, textAlign: "center", lineHeight: 1.6 }}>
                与AI智能体对话，执行开发、运维、分析等任务
              </div>
              <button
                className="btn-acc es-cta"
                onClick={() => setPickerOpen(true)}
              >
                + 新建会话
              </button>
              {error && (
                <div className="inline-err" style={{ marginTop: 14 }}>
                  <span>⚠ {error}</span>
                  <button className="x-btn" onClick={() => setError(null)} aria-label="关闭">
                    ✕
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* RIGHT: meta + actions */}
        <div className="agent-hub-col col-meta">
          <div className="agent-hub-head">
            <span className="h-title">会话信息</span>
          </div>
          <div className="agent-hub-body">
            {current ? (
              <>
                <div className="meta-section">
                  <div className="meta-title">运行状态</div>
                  <Row k="ID" v={current.id} mono />
                  <Row k="Agent" v={current.agent_id} />
                  <Row k="模型" v={current.model || "-"} />
                  <Row k="运行" v={current.live ? "● 在线" : current.status} accent={current.live} />
                  <Row k="工作目录" v={current.workdir || "(home)"} />
                  <Row k="Token" v={String(current.token_estimate)} />
                  <Row k="创建" v={current.created_at.replace("T", " ").slice(0, 16)} />
                  {current.parent_id && (
                    <Row k="父会话" v={current.parent_id} mono />
                  )}
                  {current.branch_anchor_seq != null && (
                    <Row k="分支锚点" v={"seq " + current.branch_anchor_seq} />
                  )}
                </div>

                <div className="meta-section">
                  <div className="meta-title">操作</div>
                  <div className="meta-actions">
                    <button className="tbtn" onClick={onCompact} disabled={busy} title="将历史压缩为摘要">
                      <span className="ic">◇</span> 压缩历史
                    </button>
                    <button className="tbtn" onClick={onBranch} disabled={busy} title="从当前最新消息分支">
                      <span className="ic">⎇</span> 创建分支
                    </button>
                    <button className="tbtn" onClick={onStopPty} disabled={!current.live} title="结束 PTY 进程">
                      <span className="ic">▣</span> 关闭 PTY
                    </button>
                    <button className="tbtn" onClick={onArchive} title={current.archived ? "取消归档" : "归档"}>
                      <span className="ic">◧</span> {current.archived ? "取消归档" : "归档会话"}
                    </button>
                    <button className="tbtn danger" onClick={onDelete} title="删除会话">
                      <span className="ic">✕</span> 删除会话
                    </button>
                  </div>
                </div>

                {current.children && current.children.length > 0 && (
                  <div className="meta-section">
                    <div className="meta-title">分支</div>
                    <div className="meta-actions">
                      {current.children.map((c) => (
                        <button
                          key={c.id}
                          className="tbtn"
                          onClick={() => {
                            setCurrentId(c.id);
                            closeDrawers();
                          }}
                          title={c.id}
                        >
                          <span className="ic">↳</span>
                          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                            {c.title}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="meta-section" style={{ color: "var(--t3)", fontSize: 10 }}>
                未选择会话
              </div>
            )}
          </div>
        </div>
      </div>

      <AgentPicker open={pickerOpen} onClose={() => setPickerOpen(false)} onConfirm={onCreate} />
    </div>
  );
}

function Row({ k, v, accent, mono }: { k: string; v: string; accent?: boolean; mono?: boolean }) {
  return (
    <div className="meta-row">
      <span className="mk">{k}</span>
      <span
        className={"mv" + (mono ? " mono" : "")}
        style={accent ? { color: "var(--acc)" } : undefined}
        title={v}
      >
        {v}
      </span>
    </div>
  );
}
