import { useMemo, useState } from "react";
import type { Project } from "../../../../api/projects";
import { useGitController } from "./useGitController";
import { getGitBranches, checkoutBranch, createBranch, type GitFile } from "../../../../api/git";

type Props = {
  project: Project;
};

/**
 * Git panel for the workspace.
 *
 * Layout:
 *   ┌─ branch bar (branch · ahead/behind · refresh) ─┐
 *   │                                                  │
 *   ├─ file list (grouped) ──┬─ diff viewer ──────────│
 *   │ Staged                  │  +/− colored hunks    │
 *   │ Unstaged                │                        │
 *   │ Untracked               │                        │
 *   ├──────────────────────────┴────────────────────────┤
 *   │ commit composer (textarea + commit button)        │
 *   └────────────────────────────────────────────────────┘
 *
 * Scope: status + diff + stage/unstage/discard/commit. No push/pull/merge
 * — those happen in the terminal.
 */
export default function GitPanel({ project }: Props) {
  const ctrl = useGitController(project.id);
  const [message, setMessage] = useState("");

  const grouped = useMemo(() => {
    const out = { staged: [] as GitFile[], unstaged: [] as GitFile[], untracked: [] as GitFile[] };
    for (const f of ctrl.status?.files || []) {
      if (f.status === "?") out.untracked.push(f);
      else {
        if (f.staged) out.staged.push(f);
        if (f.unstaged) out.unstaged.push(f);
      }
    }
    return out;
  }, [ctrl.status]);

  const stagedCount = grouped.staged.length;
  const totalCount = ctrl.status?.files.length || 0;

  if (!ctrl.status) {
    return (
      <div className="git-panel">
        <div className="git-empty">
          {ctrl.loadingStatus ? "加载 git 状态中…" : "等待项目…"}
        </div>
      </div>
    );
  }

  if (!ctrl.status.is_repo) {
    return (
      <div className="git-panel">
        <div className="git-empty">
          <div style={{ fontSize: 24, marginBottom: 10 }}>⎇</div>
          <div>{ctrl.status.error || "该目录不是 git 仓库"}</div>
          <div style={{ marginTop: 12, fontSize: 10, color: "var(--t3)" }}>
            <code>{ctrl.status.path}</code>
          </div>
          <div style={{ marginTop: 14, fontSize: 10.5, color: "var(--t3)" }}>
            在「终端」tab 内执行 <code>git init</code> 后回来刷新。
          </div>
          <button className="tbtn" onClick={ctrl.refresh} style={{ marginTop: 16 }}>↻ 刷新</button>
        </div>
      </div>
    );
  }

  const onCommit = async () => {
    if (!message.trim() || stagedCount === 0 || ctrl.busyOp) return;
    const ok = await ctrl.commit(message.trim());
    if (ok) setMessage("");
  };

  return (
    <div className="git-panel">
      <BranchBar status={ctrl.status} projectId={project.id} onRefresh={ctrl.refresh} onSwitched={ctrl.refresh} busy={ctrl.busyOp || ctrl.loadingStatus} />
      {ctrl.err && (
        <div className="git-err">
          ⚠ {ctrl.err}
          <button className="x-btn" onClick={ctrl.clearErr} aria-label="关闭">✕</button>
        </div>
      )}
      <div className="git-body">
        <FileColumn
          grouped={grouped}
          selected={ctrl.selected}
          onSelect={ctrl.select}
          onStage={(p) => ctrl.stage([p])}
          onUnstage={(p) => ctrl.unstage([p])}
          onDiscard={async (p) => {
            if (!confirm(`确定丢弃 ${p} 的工作区改动？`)) return;
            await ctrl.discard([p]);
          }}
          onStageAll={() => {
            const paths = [...grouped.unstaged, ...grouped.untracked].map((f) => f.path);
            if (paths.length) ctrl.stage(paths);
          }}
          onUnstageAll={() => {
            const paths = grouped.staged.map((f) => f.path);
            if (paths.length) ctrl.unstage(paths);
          }}
          busy={ctrl.busyOp}
        />
        <DiffPane file={ctrl.selected} diff={ctrl.diff?.diff || ""} loading={ctrl.loadingDiff} truncated={!!ctrl.diff?.truncated} />
      </div>
      <CommitComposer
        message={message}
        setMessage={setMessage}
        stagedCount={stagedCount}
        totalCount={totalCount}
        busy={ctrl.busyOp}
        onCommit={onCommit}
      />
    </div>
  );
}

// ─── Branch / refresh bar ───────────────────────────────────────────────────

function BranchBar({ status, projectId, onRefresh, onSwitched, busy }: {
  status: import("../../../../api/git").GitStatus;
  projectId: string;
  onRefresh: () => void;
  onSwitched: () => void;
  busy: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [branches, setBranches] = useState<string[]>([]);
  const [loadingBranches, setLoadingBranches] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const toggle = async () => {
    if (open) { setOpen(false); return; }
    setOpen(true); setErr(null); setLoadingBranches(true);
    try {
      const r = await getGitBranches(projectId);
      setBranches(r.branches);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "加载分支失败");
    } finally {
      setLoadingBranches(false);
    }
  };

  const doCheckout = async (name: string) => {
    if (name === status.branch) { setOpen(false); return; }
    setSwitching(true); setErr(null);
    try {
      await checkoutBranch(projectId, name);
      setOpen(false);
      onSwitched();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "切换失败（可能有未提交改动）");
    } finally {
      setSwitching(false);
    }
  };

  const doCreate = async () => {
    const name = window.prompt("新分支名（基于当前分支创建并切换）");
    if (!name?.trim()) return;
    setSwitching(true); setErr(null);
    try {
      await createBranch(projectId, name.trim());
      setOpen(false);
      onSwitched();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "创建失败");
    } finally {
      setSwitching(false);
    }
  };

  return (
    <div className="git-branch-bar">
      <span className="git-branch-icon">⎇</span>
      <button className="git-branch-name git-branch-btn" onClick={toggle} disabled={busy || switching} title="切换分支">
        {status.branch || "(detached HEAD)"} <span style={{ fontSize: 8, opacity: 0.6 }}>▾</span>
      </button>
      {status.ahead > 0 && <span className="git-ahead" title="本地领先远端">↑{status.ahead}</span>}
      {status.behind > 0 && <span className="git-behind" title="本地落后远端">↓{status.behind}</span>}
      <span className="git-branch-spacer" />
      <span className="git-branch-path" title={status.path}>{status.path}</span>
      <button className="tbtn" onClick={onRefresh} disabled={busy}>{busy ? "…" : "↻"}</button>
      {open && (
        <>
          <div className="git-branch-backdrop" onClick={() => setOpen(false)} />
          <div className="git-branch-dropdown">
            <div className="git-branch-dropdown-head">
              <span>切换分支</span>
              <button className="tbtn" onClick={doCreate} disabled={switching}>+ 新建</button>
            </div>
            {err && <div className="git-branch-dropdown-err">{err}</div>}
            {loadingBranches ? (
              <div className="git-branch-dropdown-empty">加载中…</div>
            ) : branches.length === 0 ? (
              <div className="git-branch-dropdown-empty">无本地分支</div>
            ) : (
              branches.map((b) => (
                <button
                  key={b}
                  className={"git-branch-item" + (b === status.branch ? " active" : "")}
                  onClick={() => doCheckout(b)}
                  disabled={switching}
                >
                  <span className="git-branch-item-mark">{b === status.branch ? "●" : "○"}</span>
                  <span className="git-branch-item-name">{b}</span>
                </button>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ─── Left column: file list ─────────────────────────────────────────────────

function FileColumn({
  grouped, selected, onSelect,
  onStage, onUnstage, onDiscard,
  onStageAll, onUnstageAll,
  busy,
}: {
  grouped: { staged: GitFile[]; unstaged: GitFile[]; untracked: GitFile[] };
  selected: GitFile | null;
  onSelect: (f: GitFile) => void;
  onStage: (p: string) => void;
  onUnstage: (p: string) => void;
  onDiscard: (p: string) => void;
  onStageAll: () => void;
  onUnstageAll: () => void;
  busy: boolean;
}) {
  return (
    <div className="git-files">
      <FileGroup
        title="已暂存"
        count={grouped.staged.length}
        files={grouped.staged}
        action={grouped.staged.length ? { label: "全部取消暂存", onClick: onUnstageAll, disabled: busy } : null}
        selected={selected}
        onSelect={onSelect}
        rowAction={(f) => ({ label: "↶", title: "取消暂存", onClick: () => onUnstage(f.path) })}
        accent="acc"
      />
      <FileGroup
        title="工作区改动"
        count={grouped.unstaged.length}
        files={grouped.unstaged}
        action={grouped.unstaged.length || grouped.untracked.length
          ? { label: "全部暂存", onClick: onStageAll, disabled: busy }
          : null}
        selected={selected}
        onSelect={onSelect}
        rowAction={(f) => ({ label: "+", title: "暂存", onClick: () => onStage(f.path) })}
        secondaryAction={(f) => ({ label: "✕", title: "丢弃工作区改动", danger: true, onClick: () => onDiscard(f.path) })}
        accent="amber"
      />
      <FileGroup
        title="未跟踪"
        count={grouped.untracked.length}
        files={grouped.untracked}
        action={null}
        selected={selected}
        onSelect={onSelect}
        rowAction={(f) => ({ label: "+", title: "添加并暂存", onClick: () => onStage(f.path) })}
        accent="blue"
      />
      {grouped.staged.length + grouped.unstaged.length + grouped.untracked.length === 0 && (
        <div className="git-files-empty">工作区干净 · 没有变更</div>
      )}
    </div>
  );
}

function FileGroup({
  title, count, files, action,
  selected, onSelect, rowAction, secondaryAction, accent,
}: {
  title: string;
  count: number;
  files: GitFile[];
  action: { label: string; onClick: () => void; disabled?: boolean } | null;
  selected: GitFile | null;
  onSelect: (f: GitFile) => void;
  rowAction: (f: GitFile) => { label: string; title?: string; onClick: () => void; danger?: boolean };
  secondaryAction?: (f: GitFile) => { label: string; title?: string; onClick: () => void; danger?: boolean };
  accent: "acc" | "amber" | "blue";
}) {
  if (count === 0) return null;
  return (
    <div className={"git-file-group accent-" + accent}>
      <div className="git-file-group-head">
        <span className="git-file-group-title">{title}</span>
        <span className="git-file-group-count">{count}</span>
        {action && (
          <button className="git-mini-btn" onClick={action.onClick} disabled={action.disabled}>{action.label}</button>
        )}
      </div>
      <div className="git-file-list">
        {files.map((f) => (
          <div
            key={f.path}
            className={"git-file-row" + (selected?.path === f.path ? " selected" : "")}
            onClick={() => onSelect(f)}
            title={f.path}
          >
            <span className={"git-status-badge st-" + f.status}>{f.status}</span>
            <span className="git-file-path">{f.path}</span>
            {(() => {
              const a = rowAction(f);
              return (
                <button
                  className={"git-row-btn" + (a.danger ? " danger" : "")}
                  title={a.title}
                  onClick={(e) => { e.stopPropagation(); a.onClick(); }}
                >{a.label}</button>
              );
            })()}
            {secondaryAction && (() => {
              const a = secondaryAction(f);
              return (
                <button
                  className={"git-row-btn" + (a.danger ? " danger" : "")}
                  title={a.title}
                  onClick={(e) => { e.stopPropagation(); a.onClick(); }}
                >{a.label}</button>
              );
            })()}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Right column: diff viewer ──────────────────────────────────────────────

function DiffPane({ file, diff, loading, truncated }: {
  file: GitFile | null; diff: string; loading: boolean; truncated: boolean;
}) {
  if (!file) {
    return (
      <div className="git-diff">
        <div className="git-diff-empty">选择左侧文件查看 diff</div>
      </div>
    );
  }
  return (
    <div className="git-diff">
      <div className="git-diff-head">
        <span className={"git-status-badge st-" + file.status}>{file.status}</span>
        <span className="git-diff-path" title={file.path}>{file.path}</span>
        {truncated && <span className="git-diff-warn">⚠ 已截断到 256KB</span>}
      </div>
      <div className="git-diff-body">
        {loading ? (
          <div className="git-diff-empty">加载 diff 中…</div>
        ) : diff ? (
          <DiffText text={diff} />
        ) : (
          <div className="git-diff-empty">无 diff（可能是新增/删除二进制文件）</div>
        )}
      </div>
    </div>
  );
}

/** Color +/- lines without doing a full syntax parser. */
function DiffText({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <pre className="git-diff-pre">
      {lines.map((ln, i) => {
        let cls = "df-ctx";
        if (ln.startsWith("+++") || ln.startsWith("---") || ln.startsWith("diff ")) cls = "df-meta";
        else if (ln.startsWith("@@")) cls = "df-hunk";
        else if (ln.startsWith("+")) cls = "df-add";
        else if (ln.startsWith("-")) cls = "df-del";
        return <span key={i} className={cls}>{ln + "\n"}</span>;
      })}
    </pre>
  );
}

// ─── Bottom: commit composer ────────────────────────────────────────────────

function CommitComposer({
  message, setMessage, stagedCount, totalCount, busy, onCommit,
}: {
  message: string; setMessage: (m: string) => void;
  stagedCount: number; totalCount: number; busy: boolean; onCommit: () => void;
}) {
  const canCommit = stagedCount > 0 && message.trim().length > 0 && !busy;
  return (
    <div className="git-composer">
      <textarea
        className="git-composer-input"
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder={stagedCount > 0
          ? `为已暂存的 ${stagedCount} 个文件写一条提交信息…\n（Cmd/Ctrl+Enter 提交）`
          : "先暂存改动再提交"}
        disabled={stagedCount === 0 || busy}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && canCommit) {
            e.preventDefault();
            onCommit();
          }
        }}
      />
      <div className="git-composer-foot">
        <span className="git-composer-status">
          {totalCount === 0 ? "工作区干净" : `已暂存 ${stagedCount} / ${totalCount}`}
        </span>
        <button
          className="tbtn tbtn-acc"
          onClick={onCommit}
          disabled={!canCommit}
        >
          {busy ? "提交中…" : "✓ 提交"}
        </button>
      </div>
    </div>
  );
}
