import { useCallback, useRef, useState } from "react";
import { api } from "../../../../api/client";

type Options = {
  /** Current directory uploads should land in. */
  path: string;
  refresh: () => void;
  onError: (msg: string) => void;
  onInfo?: (msg: string) => void;
};

type Result = {
  uploading: boolean;
  progress: number;       // 0..1, only valid while uploading
  isDragOver: boolean;
  /** Wire these handlers onto the drop zone div. */
  dragProps: {
    onDragEnter: (e: React.DragEvent) => void;
    onDragOver: (e: React.DragEvent) => void;
    onDragLeave: (e: React.DragEvent) => void;
    onDrop: (e: React.DragEvent) => void;
  };
  /** Click-trigger flow: openPicker() opens the hidden <input>; then onChange fires. */
  inputProps: {
    ref: React.RefObject<HTMLInputElement>;
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
    type: "file";
    hidden: true;
    multiple: true;
  };
  openPicker: () => void;
};

/**
 * Drag-and-drop + click-to-pick upload.
 *
 * Handles single or multi-file batches. We track per-batch progress as
 * (completed / total) so the UI can show something useful for large
 * uploads (uniform progress per file is good enough — accurate per-byte
 * progress would require switching off axios to fetch with ReadableStream).
 */
export function useFilesUpload({ path, refresh, onError, onInfo }: Options): Result {
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [isDragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dragDepthRef = useRef(0);

  const uploadBatch = useCallback(
    async (files: File[]) => {
      if (!files.length) return;
      setUploading(true);
      setProgress(0);
      let done = 0;
      let failed = 0;
      try {
        for (const file of files) {
          try {
            const form = new FormData();
            form.append("file", file);
            await api.post("/agent-files/upload", form, {
              params: { dest: path },
              headers: { "Content-Type": "multipart/form-data" },
              onUploadProgress: (ev) => {
                if (ev.total) {
                  const overall = (done + ev.loaded / ev.total) / files.length;
                  setProgress(Math.min(1, overall));
                }
              },
            });
          } catch (e: any) {
            failed += 1;
            onError(`${file.name}: ${e?.response?.data?.detail || e?.message || "上传失败"}`);
          }
          done += 1;
          setProgress(done / files.length);
        }
        if (failed === 0) onInfo?.(`已上传 ${files.length} 个文件`);
        else if (failed < files.length) onInfo?.(`部分上传成功 (${files.length - failed}/${files.length})`);
        refresh();
      } finally {
        setUploading(false);
        // Brief pause so the user sees 100% before the bar fades.
        window.setTimeout(() => setProgress(0), 800);
      }
    },
    [onError, onInfo, path, refresh],
  );

  const onDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragDepthRef.current += 1;
    if (e.dataTransfer?.types?.includes("Files")) setDragOver(true);
  }, []);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setDragOver(false);
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragDepthRef.current = 0;
      setDragOver(false);
      const files = Array.from(e.dataTransfer?.files || []);
      if (files.length) void uploadBatch(files);
    },
    [uploadBatch],
  );

  const onInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      e.target.value = "";
      if (files.length) void uploadBatch(files);
    },
    [uploadBatch],
  );

  const openPicker = useCallback(() => {
    inputRef.current?.click();
  }, []);

  return {
    uploading,
    progress,
    isDragOver,
    dragProps: { onDragEnter, onDragOver, onDragLeave, onDrop },
    inputProps: { ref: inputRef, onChange: onInputChange, type: "file", hidden: true, multiple: true },
    openPicker,
  };
}
