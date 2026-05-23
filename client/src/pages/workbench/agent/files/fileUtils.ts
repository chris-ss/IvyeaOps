// File-related formatting + extension → icon mapping.
// Icons are intentionally Unicode glyphs (not lucide / external font) so the
// component stays self-contained and matches the existing ops-hub aesthetic.

export function formatSize(bytes: number | null | undefined): string {
  if (bytes == null) return "";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
  return (bytes / 1024 / 1024 / 1024).toFixed(1) + " GB";
}

export function formatTime(mtime: number): string {
  if (!mtime) return "";
  const d = new Date(mtime * 1000);
  const now = Date.now();
  const diff = now - d.getTime();
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return Math.floor(diff / 60_000) + "分钟前";
  if (diff < 86_400_000) return Math.floor(diff / 3_600_000) + "小时前";
  if (diff < 7 * 86_400_000) return Math.floor(diff / 86_400_000) + "天前";
  return d.toLocaleDateString("zh-CN", { year: "2-digit", month: "numeric", day: "numeric" });
}

const EXT_GROUPS: Array<{ exts: string[]; icon: string; color?: string }> = [
  // Source code
  { exts: ["ts", "tsx"], icon: "TS", color: "var(--blue)" },
  { exts: ["js", "jsx", "mjs", "cjs"], icon: "JS", color: "#facc15" },
  { exts: ["py"], icon: "PY", color: "var(--blue)" },
  { exts: ["go"], icon: "GO", color: "#06b6d4" },
  { exts: ["rs"], icon: "RS", color: "#f97316" },
  { exts: ["java", "kt"], icon: "JV", color: "#f97316" },
  { exts: ["rb"], icon: "RB", color: "var(--red)" },
  { exts: ["php"], icon: "PHP", color: "#8b5cf6" },
  { exts: ["sh", "bash", "zsh"], icon: "SH", color: "var(--acc)" },
  // Markup / config
  { exts: ["md", "markdown"], icon: "MD", color: "var(--t2)" },
  { exts: ["json", "yaml", "yml", "toml", "ini", "conf", "cfg"], icon: "{}", color: "var(--t3)" },
  { exts: ["html", "htm"], icon: "<>", color: "#f97316" },
  { exts: ["css", "scss", "sass", "less"], icon: "CSS", color: "var(--blue)" },
  { exts: ["xml"], icon: "<>", color: "var(--t3)" },
  { exts: ["sql"], icon: "SQL", color: "#facc15" },
  // Data
  { exts: ["csv", "tsv"], icon: "≡", color: "var(--acc)" },
  { exts: ["xlsx", "xls"], icon: "≡", color: "var(--acc)" },
  { exts: ["sqlite", "sqlite3", "db"], icon: "DB", color: "#8b5cf6" },
  // Media
  { exts: ["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico"], icon: "🖼", color: "#ec4899" },
  { exts: ["mp4", "mov", "webm", "avi", "mkv"], icon: "▶", color: "#ec4899" },
  { exts: ["mp3", "wav", "flac", "ogg"], icon: "♪", color: "#ec4899" },
  // Archives / binaries
  { exts: ["zip", "tar", "gz", "tgz", "bz2", "xz", "7z", "rar"], icon: "📦", color: "var(--amber)" },
  { exts: ["pdf"], icon: "PDF", color: "var(--red)" },
  // Logs
  { exts: ["log", "out", "err"], icon: "≣", color: "var(--t3)" },
];

export type IconSpec = { glyph: string; color?: string };

export function iconForFile(name: string, isDir: boolean): IconSpec {
  if (isDir) return { glyph: "📁", color: "var(--amber)" };
  const dot = name.lastIndexOf(".");
  if (dot < 0) return { glyph: "📄", color: "var(--t3)" };
  const ext = name.slice(dot + 1).toLowerCase();
  for (const g of EXT_GROUPS) {
    if (g.exts.includes(ext)) return { glyph: g.icon, color: g.color };
  }
  return { glyph: "📄", color: "var(--t3)" };
}

export function isImage(name: string): boolean {
  return /\.(png|jpe?g|gif|webp|svg|bmp|ico)$/i.test(name);
}

/** Split an absolute path into breadcrumb segments. */
export function breadcrumbSegments(path: string): { name: string; full: string }[] {
  // Normalize: drop trailing slash unless root
  const norm = path.replace(/\/+$/, "") || "/";
  if (norm === "/") return [{ name: "/", full: "/" }];
  const parts = norm.split("/").filter(Boolean);
  const out: { name: string; full: string }[] = [{ name: "/", full: "/" }];
  let acc = "";
  for (const p of parts) {
    acc += "/" + p;
    out.push({ name: p, full: acc });
  }
  return out;
}
