import { useEffect, useMemo, useRef, useState } from "react";
import type { Project, ProjectSession } from "../../../api/projects";
import { TAB_LABELS, type TabKey } from "./tabs";

export type Command =
  | { kind: "project"; project: Project }
  | { kind: "session"; project: Project; session: ProjectSession }
  | { kind: "tab"; tab: TabKey }
  | { kind: "action"; id: string; label: string; hint?: string; onRun: () => void };

type Props = {
  open: boolean;
  onClose: () => void;
  projects: Project[];
  sessionsByProject: Record<string, ProjectSession[] | undefined>;
  currentProjectId: string | null;
  availableTabs: TabKey[];
  onSelectProject: (projectId: string) => void;
  onSelectSession: (projectId: string, session: ProjectSession) => void;
  onSwitchTab: (tab: TabKey) => void;
  onNewSession: () => void;
  onRefresh: () => void;
  onOpenSettings: () => void;
};

/**
 * ⌘K / Ctrl+K command palette.
 *
 * Aggregates everything the user might want to jump to: projects, their
 * sessions (if already fetched into memory by the sidebar), the current
 * session's tabs, and a few global actions. Filtering is "characters in
 * order" — typing "wr" matches "市场调研报告" (because 调=报+研 etc. → no,
 * actually just substring) — well, let me keep it as a case-insensitive
 * substring match on the searchable text. Fuzzy-fuzzy isn't worth the
 * complexity for a UI of this size.
 *
 * Keyboard:
 *   – Esc        close
 *   – ↑/↓        move highlight
 *   – Enter      run highlighted command
 *   – Tab        cycle category (skipped — we render a flat list, simpler)
 */
export default function CommandPalette({
  open, onClose,
  projects, sessionsByProject, currentProjectId, availableTabs,
  onSelectProject, onSelectSession, onSwitchTab,
  onNewSession, onRefresh, onOpenSettings,
}: Props) {
  const [q, setQ] = useState("");
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset state every time we open.
  useEffect(() => {
    if (open) {
      setQ("");
      setHighlight(0);
      // Focus the input next frame so the modal's mount animation doesn't steal it.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const commands: Command[] = useMemo(() => {
    const out: Command[] = [];

    // Global actions first — always visible at top so Esc-K-Enter
    // pattern stays predictable for power users.
    out.push({
      kind: "action", id: "new-session",
      label: "+ 新建会话", hint: "在当前项目下创建新 hub 会话",
      onRun: onNewSession,
    });
    out.push({
      kind: "action", id: "refresh",
      label: "↻ 刷新项目列表", hint: "重扫 ~/.claude / ~/.codex / agent_sessions",
      onRun: onRefresh,
    });
    out.push({
      kind: "action", id: "open-settings",
      label: "⚙ 打开系统配置", hint: "/hub-settings",
      onRun: onOpenSettings,
    });

    // Tabs for the currently-active session
    for (const t of availableTabs) {
      out.push({ kind: "tab", tab: t });
    }

    // Projects
    for (const p of projects) {
      out.push({ kind: "project", project: p });
    }

    // Sessions (only those already fetched). Lazy-loading inside the
    // palette would require waterfall HTTP calls per keystroke, so we
    // stick to what the sidebar already has.
    for (const p of projects) {
      const sessions = sessionsByProject[p.id];
      if (!sessions) continue;
      for (const s of sessions) {
        out.push({ kind: "session", project: p, session: s });
      }
    }

    return out;
  }, [projects, sessionsByProject, availableTabs, onNewSession, onRefresh, onOpenSettings]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return commands;
    return commands.filter((c) => searchText(c).toLowerCase().includes(needle));
  }, [commands, q]);

  // Reset highlight when filtered set changes
  useEffect(() => { setHighlight(0); }, [q]);

  if (!open) return null;

  const run = (c: Command) => {
    if (c.kind === "project") onSelectProject(c.project.id);
    else if (c.kind === "session") onSelectSession(c.project.id, c.session);
    else if (c.kind === "tab") onSwitchTab(c.tab);
    else if (c.kind === "action") c.onRun();
    onClose();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(filtered.length - 1, h + 1));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(0, h - 1));
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const target = filtered[highlight];
      if (target) run(target);
      return;
    }
  };

  return (
    <div className="cmdk-backdrop" onClick={onClose}>
      <div className="cmdk-modal" onClick={(e) => e.stopPropagation()} onKeyDown={onKeyDown}>
        <div className="cmdk-input-row">
          <span className="cmdk-icon">⌘K</span>
          <input
            ref={inputRef}
            className="cmdk-input"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索项目 / 会话 / tab / 命令…"
            spellCheck={false}
            autoComplete="off"
          />
          <button className="cmdk-esc-hint" onClick={onClose}>Esc</button>
        </div>
        <div className="cmdk-list">
          {filtered.length === 0 ? (
            <div className="cmdk-empty">没有匹配项</div>
          ) : (
            filtered.map((c, i) => (
              <CommandRow
                key={rowKey(c, i)}
                cmd={c}
                active={i === highlight}
                isCurrentProject={c.kind === "project" && c.project.id === currentProjectId}
                onMouseEnter={() => setHighlight(i)}
                onClick={() => run(c)}
              />
            ))
          )}
        </div>
        <div className="cmdk-footer">
          <span><kbd>↑↓</kbd> 选择</span>
          <span><kbd>Enter</kbd> 确认</span>
          <span><kbd>Esc</kbd> 关闭</span>
          <span className="cmdk-footer-spacer" />
          <span>{filtered.length} / {commands.length} 项</span>
        </div>
      </div>
    </div>
  );
}

function rowKey(c: Command, i: number): string {
  if (c.kind === "project") return `project:${c.project.id}`;
  if (c.kind === "session") return `session:${c.project.id}:${c.session.id}`;
  if (c.kind === "tab") return `tab:${c.tab}`;
  if (c.kind === "action") return `action:${c.id}`;
  return `i:${i}`;
}

function searchText(c: Command): string {
  if (c.kind === "project") return `${c.project.name} ${c.project.path}`;
  if (c.kind === "session") return `${c.session.title} ${c.session.source} ${c.project.name}`;
  if (c.kind === "tab") return `${TAB_LABELS[c.tab]} tab`;
  if (c.kind === "action") return `${c.label} ${c.hint || ""}`;
  return "";
}

function CommandRow({ cmd, active, isCurrentProject, onMouseEnter, onClick }: {
  cmd: Command;
  active: boolean;
  isCurrentProject: boolean;
  onMouseEnter: () => void;
  onClick: () => void;
}) {
  let icon: string, primary: React.ReactNode, secondary: string | null = null, kindLabel: string;
  if (cmd.kind === "project") {
    icon = "📁";
    primary = cmd.project.name;
    secondary = cmd.project.path + (isCurrentProject ? "  · 当前" : "");
    kindLabel = "项目";
  } else if (cmd.kind === "session") {
    icon = cmd.session.source === "hub" ? "✦" : cmd.session.source === "claude" ? "C" : cmd.session.source === "codex" ? "X" : "?";
    primary = cmd.session.title;
    secondary = `${cmd.project.name} · ${cmd.session.source}`;
    kindLabel = "会话";
  } else if (cmd.kind === "tab") {
    icon = "↹";
    primary = `切到「${TAB_LABELS[cmd.tab]}」tab`;
    kindLabel = "TAB";
  } else {
    icon = "▸";
    primary = cmd.label;
    secondary = cmd.hint || null;
    kindLabel = "动作";
  }
  return (
    <div
      className={"cmdk-row" + (active ? " active" : "")}
      onMouseEnter={onMouseEnter}
      onClick={onClick}
    >
      <span className="cmdk-row-icon">{icon}</span>
      <div className="cmdk-row-body">
        <div className="cmdk-row-primary">{primary}</div>
        {secondary && <div className="cmdk-row-secondary">{secondary}</div>}
      </div>
      <span className={"cmdk-row-kind kind-" + (cmd.kind)}>{kindLabel}</span>
    </div>
  );
}
