import type { ProjectSource } from "../../../api/projects";

export type TabKey = "chat" | "shell" | "files" | "transcript" | "git";

export const TAB_LABELS: Record<TabKey, string> = {
  chat: "聊天",
  shell: "终端",
  files: "文件",
  transcript: "记录",
  git: "Git",
};

/** Single-character glyphs used by the mobile bottom nav. */
export const TAB_GLYPHS: Record<TabKey, string> = {
  chat: "✦",
  shell: "▶",
  files: "▣",
  transcript: "≡",
  git: "⎇",
};

export function availableTabsFor(source: ProjectSource | string | null | undefined): TabKey[] {
  if (source === "hub") return ["chat", "shell", "files", "git"];
  if (source === "claude" || source === "codex") return ["transcript", "files", "git"];
  return ["files"];
}
