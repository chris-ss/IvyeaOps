import { useCallback, useState } from "react";
import { api } from "../../../../api/client";

type Options = {
  refresh: () => void;
  onError: (msg: string) => void;
  onInfo?: (msg: string) => void;
};

type Result = {
  busy: boolean;
  mkdir: (parent: string, name: string) => Promise<void>;
  rename: (path: string, newName: string) => Promise<void>;
  remove: (path: string) => Promise<void>;
  copyPath: (path: string) => Promise<void>;
  download: (path: string) => void;
};

/**
 * Server-mutating file operations. Each method is sequenced through a
 * single `busy` flag — the UI disables conflicting buttons while one is
 * in flight (prevents accidental double-clicks producing duplicate
 * mkdir calls etc).
 *
 * All errors are surfaced via `onError`; success paths trigger `refresh()`
 * so the caller doesn't have to remember.
 */
export function useFilesOps({ refresh, onError, onInfo }: Options): Result {
  const [busy, setBusy] = useState(false);

  const wrap = useCallback(
    async (fn: () => Promise<void>) => {
      if (busy) return;
      setBusy(true);
      try {
        await fn();
      } finally {
        setBusy(false);
      }
    },
    [busy],
  );

  const mkdir = useCallback(
    (parent: string, name: string) =>
      wrap(async () => {
        try {
          await api.post("/agent-files/mkdir", null, { params: { path: parent, name } });
          onInfo?.("已创建目录");
          refresh();
        } catch (e: any) {
          onError(e?.response?.data?.detail || e?.message || "创建目录失败");
        }
      }),
    [onError, onInfo, refresh, wrap],
  );

  const rename = useCallback(
    (path: string, newName: string) =>
      wrap(async () => {
        try {
          await api.post("/agent-files/rename", null, {
            params: { path, new_name: newName },
          });
          onInfo?.("已重命名");
          refresh();
        } catch (e: any) {
          onError(e?.response?.data?.detail || e?.message || "重命名失败");
        }
      }),
    [onError, onInfo, refresh, wrap],
  );

  const remove = useCallback(
    (path: string) =>
      wrap(async () => {
        try {
          await api.post("/agent-files/delete", null, { params: { path } });
          onInfo?.("已删除");
          refresh();
        } catch (e: any) {
          onError(e?.response?.data?.detail || e?.message || "删除失败");
        }
      }),
    [onError, onInfo, refresh, wrap],
  );

  const copyPath = useCallback(
    async (path: string) => {
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(path);
          onInfo?.("路径已复制");
        } else {
          window.prompt("复制路径:", path);
        }
      } catch {
        window.prompt("复制路径:", path);
      }
    },
    [onInfo],
  );

  const download = useCallback((path: string) => {
    window.open(`/api/agent-files/download?path=${encodeURIComponent(path)}`, "_blank");
  }, []);

  return { busy, mkdir, rename, remove, copyPath, download };
}
