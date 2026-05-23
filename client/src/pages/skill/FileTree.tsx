import { useMemo } from "react";
import { LinkedFile } from "../../api/skill";

export type FileTreeProps = {
  files: LinkedFile[];
  /** The current selected path, e.g. "SKILL.md" or "references/api.md". */
  selected: string;
  onSelect: (path: string) => void;
  /** Dirty paths get a blue dot. */
  dirty?: Set<string>;
};

type TreeNode = {
  name: string;
  fullPath: string;
  kind: "dir" | "file";
  children: TreeNode[];
  size?: number;
  is_binary?: boolean;
};

function fmtSize(n?: number): string {
  if (n == null) return "";
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)}K`;
  return `${(n / 1024 / 1024).toFixed(1)}M`;
}

function buildTree(files: LinkedFile[]): TreeNode {
  const root: TreeNode = { name: "", fullPath: "", kind: "dir", children: [] };
  for (const f of files) {
    const segments = f.path.split("/").filter(Boolean);
    let cur = root;
    segments.forEach((seg, i) => {
      const isLast = i === segments.length - 1;
      let child = cur.children.find((c) => c.name === seg);
      if (!child) {
        child = {
          name: seg,
          fullPath: segments.slice(0, i + 1).join("/"),
          kind: isLast ? "file" : "dir",
          children: [],
          size: isLast ? f.size : undefined,
          is_binary: isLast ? f.is_binary : undefined,
        };
        cur.children.push(child);
      }
      cur = child;
    });
  }
  // Sort: dirs first, files after; both alphabetical.
  const sortRec = (n: TreeNode) => {
    n.children.sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === "dir" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    n.children.forEach(sortRec);
  };
  sortRec(root);
  return root;
}

export default function FileTree({ files, selected, onSelect, dirty }: FileTreeProps) {
  // SKILL.md might not appear in `linked_files` (backend returns it via
  // content_body). We prepend it so it's always visible at the top.
  const all: LinkedFile[] = useMemo(() => {
    const hasSkillMd = files.some((f) => f.path === "SKILL.md");
    if (hasSkillMd) return files;
    return [
      { path: "SKILL.md", size: 0, mtime: "", is_binary: false },
      ...files,
    ];
  }, [files]);

  const tree = useMemo(() => buildTree(all), [all]);

  return (
    <div className="sks-ft">
      {renderNodes(tree.children, 0, selected, onSelect, dirty)}
    </div>
  );
}

function renderNodes(
  nodes: TreeNode[],
  depth: number,
  selected: string,
  onSelect: (p: string) => void,
  dirty?: Set<string>,
): JSX.Element[] {
  return nodes.map((n) => {
    const isSelected = n.kind === "file" && n.fullPath === selected;
    const isDirtyFile = n.kind === "file" && dirty?.has(n.fullPath);
    if (n.kind === "dir") {
      return (
        <div key={n.fullPath} className="sks-ft-group">
          <div className="sks-ft-dir" style={{ paddingLeft: 6 + depth * 10 }}>
            <span className="ic">▸</span>
            <span className="nm">{n.name}</span>
          </div>
          {renderNodes(n.children, depth + 1, selected, onSelect, dirty)}
        </div>
      );
    }
    return (
      <div
        key={n.fullPath}
        className={"sks-ft-file" + (isSelected ? " active" : "")}
        style={{ paddingLeft: 10 + depth * 10 }}
        onClick={() => onSelect(n.fullPath)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(n.fullPath)}
        title={n.fullPath}
      >
        <span className="ic">{n.is_binary ? "▦" : "≡"}</span>
        <span className="nm">{n.name}</span>
        {isDirtyFile && <span className="dot" title="未保存" />}
        <span className="sz">{fmtSize(n.size)}</span>
      </div>
    );
  });
}
