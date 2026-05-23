import { useCallback, useEffect, useRef, useState } from "react";
import { useConfirm } from "../../../../components/ConfirmDialog";
import { useFilesData, type FileItem } from "./useFilesData";
import { useFilesOps } from "./useFilesOps";
import { useFilesUpload } from "./useFilesUpload";
import {
  breadcrumbSegments,
  formatSize,
  formatTime,
  iconForFile,
} from "./fileUtils";

type Props = {
  initialPath?: string;
};

type InlineEdit =
  | { mode: "none" }
  | { mode: "rename"; target: string; current: string; value: string }
  | { mode: "create"; type: "file" | "folder"; parent: string; value: string };

/**
 * Agent file browser.
 *
 * Layout (top-to-bottom inside the flex column):
 *   1. Breadcrumb / nav row
 *   2. Toolbar (新建 / 上传 / 刷新)
 *   3. Optional inline-create row (when user clicks 新建)
 *   4. Scrolling file list (this is the part that "couldn't scroll" before)
 *   5. Status footer with selected entry info
 *
 * Hooks split responsibility cleanly:
 *   useFilesData    – list + navigate + refresh, AbortController-guarded
 *   useFilesOps     – mkdir / rename / delete / copyPath / download
 *   useFilesUpload  – click-to-pick + drag-drop, batch upload with progress
 *
 * No use of position:absolute hacks: the scrollable region is just
 * `flex:1; min-height:0; overflow:auto` — works because the parent chain
 * (.agent-files, the column container) also runs flex:column with
 * min-height:0.
 */
export default function AgentFiles({ initialPath }: Props) {
  const confirm = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const infoTimerRef = useRef<number | null>(null);

  const setInfoFlash = useCallback((msg: string) => {
    if (infoTimerRef.current) window.clearTimeout(infoTimerRef.current);
    setInfo(msg);
    infoTimerRef.current = window.setTimeout(() => setInfo(null), 2500);
  }, []);

  useEffect(() => () => {
    if (infoTimerRef.current) window.clearTimeout(infoTimerRef.current);
  }, []);

  const { path, items, loading, error: loadError, navigate, refresh } = useFilesData(
    initialPath || "/root",
  );

  useEffect(() => { if (loadError) setError(loadError); }, [loadError]);

  const ops = useFilesOps({
    refresh,
    onError: setError,
    onInfo: setInfoFlash,
  });

  const upload = useFilesUpload({
    path,
    refresh,
    onError: setError,
    onInfo: setInfoFlash,
  });

  const [edit, setEdit] = useState<InlineEdit>({ mode: "none" });
  const editInputRef = useRef<HTMLInputElement>(null);

  // Focus inline-edit input when it appears.
  useEffect(() => {
    if (edit.mode !== "none") editInputRef.current?.focus();
  }, [edit.mode]);

  const join = (base: string, name: string) => (base.endsWith("/") ? base + name : base + "/" + name);

  const goUp = () => {
    if (path === "/") return;
    const parent = path.replace(/\/[^/]+\/?$/, "") || "/";
    navigate(parent);
  };

  const enterDir = (name: string) => navigate(join(path, name));

  const startRename = (it: FileItem) => {
    setEdit({ mode: "rename", target: join(path, it.name), current: it.name, value: it.name });
  };

  const startCreate = (type: "file" | "folder") => {
    setEdit({ mode: "create", type, parent: path, value: "" });
  };

  const commitEdit = async () => {
    if (edit.mode === "rename") {
      const name = edit.value.trim();
      if (!name || name === edit.current) {
        setEdit({ mode: "none" });
        return;
      }
      await ops.rename(edit.target, name);
      setEdit({ mode: "none" });
    } else if (edit.mode === "create") {
      const name = edit.value.trim();
      if (!name) {
        setEdit({ mode: "none" });
        return;
      }
      if (edit.type === "folder") {
        await ops.mkdir(edit.parent, name);
      } else {
        // We don't have an explicit "create empty file" endpoint; uploading
        // an empty blob is the cheapest way to materialize one without
        // bloating the API surface.
        const empty = new File([new Blob([""])], name, { type: "text/plain" });
        const dt = new DataTransfer();
        dt.items.add(empty);
        // Re-use uploadBatch via dragProps' onDrop simulator — simpler:
        // call the api directly here to avoid faking events.
        try {
          const form = new FormData();
          form.append("file", empty);
          const { api } = await import("../../../../api/client");
          await api.post("/agent-files/upload", form, { params: { dest: edit.parent } });
          setInfoFlash("已创建空文件");
          refresh();
        } catch (e: any) {
          setError(e?.response?.data?.detail || e?.message || "创建文件失败");
        }
      }
      setEdit({ mode: "none" });
    }
  };

  const cancelEdit = () => setEdit({ mode: "none" });

  const handleRowDoubleClick = (it: FileItem) => {
    if (it.is_dir) enterDir(it.name);
  };

  const handleConfirmDelete = async (it: FileItem) => {
    const ok = await confirm({
      title: `删除${it.is_dir ? "目录" : "文件"}`,
      message: `确定删除 ${it.is_dir ? "目录" : "文件"} "${it.name}"？` + (it.is_dir ? "\n该目录所有内容将被删除。" : ""),
      confirmText: "删除",
      danger: true,
    });
    if (!ok) return;
    await ops.remove(join(path, it.name));
  };

  const crumbs = breadcrumbSegments(path);

  return (
    <div className="agent-files" {...upload.dragProps}>
      {/* Drag overlay */}
      {upload.isDragOver && (
        <div className="agent-files-drop-overlay">
          <div className="agent-files-drop-card">
            <span style={{ fontSize: 22 }}>↑</span>
            <span>松开以上传到 <code>{path}</code></span>
          </div>
        </div>
      )}

      {/* Row 1: breadcrumb */}
      <div className="agent-files-crumbs">
        <button className="tbtn" onClick={goUp} disabled={path === "/"} title="上级目录">↑</button>
        <div className="agent-files-crumb-list">
          {crumbs.map((c, i) => (
            <span key={c.full} className="agent-files-crumb-segment">
              {i > 0 && <span className="agent-files-crumb-sep">/</span>}
              <button
                className={"agent-files-crumb-btn" + (i === crumbs.length - 1 ? " current" : "")}
                onClick={() => navigate(c.full)}
                title={c.full}
              >
                {c.name === "/" ? "根" : c.name}
              </button>
            </span>
          ))}
        </div>
        <button className="tbtn" onClick={refresh} disabled={loading} title="刷新">↻</button>
      </div>

      {/* Row 2: toolbar */}
      <div className="agent-files-toolbar">
        <button className="tbtn" onClick={() => startCreate("folder")} disabled={ops.busy}>
          + 新文件夹
        </button>
        <button className="tbtn" onClick={() => startCreate("file")} disabled={ops.busy}>
          + 新文件
        </button>
        <button className="tbtn" onClick={upload.openPicker} disabled={upload.uploading}>
          ↑ 上传
        </button>
        <input {...upload.inputProps} />
        <span className="agent-files-stats">
          {loading ? "加载中…" : `${items.length} 项`}
        </span>
      </div>

      {/* Row 3: upload progress */}
      {upload.uploading && (
        <div className="agent-files-progress">
          <div className="agent-files-progress-bar">
            <div className="agent-files-progress-fill" style={{ width: `${Math.round(upload.progress * 100)}%` }} />
          </div>
          <span>{Math.round(upload.progress * 100)}%</span>
        </div>
      )}

      {/* Flash messages */}
      {error && (
        <div className="agent-files-msg err">
          ⚠ {error}
          <button className="x-btn" onClick={() => setError(null)} aria-label="关闭">✕</button>
        </div>
      )}
      {info && <div className="agent-files-msg info">{info}</div>}

      {/* Row 4: file list */}
      <div className="agent-files-list">
        {/* Inline create row */}
        {edit.mode === "create" && (
          <div className="agent-files-row editing">
            <span className="agent-files-icon">{edit.type === "folder" ? "📁" : "📄"}</span>
            <input
              ref={editInputRef}
              className="agent-files-edit-input"
              value={edit.value}
              onChange={(e) => setEdit({ ...edit, value: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitEdit();
                if (e.key === "Escape") cancelEdit();
              }}
              onBlur={commitEdit}
              placeholder={edit.type === "folder" ? "新建文件夹..." : "新建文件..."}
            />
          </div>
        )}

        {items.map((it) => {
          const icon = iconForFile(it.name, it.is_dir);
          const isEditing = edit.mode === "rename" && edit.target.endsWith("/" + it.name);
          return (
            <div
              key={it.name}
              className={"agent-files-row" + (isEditing ? " editing" : "")}
              onClick={() => !isEditing && it.is_dir && enterDir(it.name)}
              onDoubleClick={() => handleRowDoubleClick(it)}
            >
              <span className="agent-files-icon" style={{ color: icon.color }}>{icon.glyph}</span>
              {isEditing ? (
                <input
                  ref={editInputRef}
                  className="agent-files-edit-input"
                  value={edit.value}
                  onChange={(e) => setEdit({ ...edit, value: e.target.value })}
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => {
                    e.stopPropagation();
                    if (e.key === "Enter") commitEdit();
                    if (e.key === "Escape") cancelEdit();
                  }}
                  onBlur={commitEdit}
                />
              ) : (
                <span className="agent-files-name" title={it.name}>{it.name}</span>
              )}
              <span className="agent-files-time">{formatTime(it.mtime)}</span>
              <span className="agent-files-size">{formatSize(it.size)}</span>
              <div className="agent-files-actions" onClick={(e) => e.stopPropagation()}>
                <button className="agent-files-btn" onClick={() => startRename(it)} title="重命名">✎</button>
                <button className="agent-files-btn" onClick={() => ops.copyPath(join(path, it.name))} title="复制路径">⎘</button>
                {!it.is_dir && (
                  <button className="agent-files-btn" onClick={() => ops.download(join(path, it.name))} title="下载">⬇</button>
                )}
                <button className="agent-files-btn danger" onClick={() => handleConfirmDelete(it)} title="删除">🗑</button>
              </div>
            </div>
          );
        })}

        {!items.length && !loading && !error && (
          <div className="agent-files-empty">空目录</div>
        )}
      </div>
    </div>
  );
}
