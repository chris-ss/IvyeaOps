import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../../api/client";

export type FileItem = {
  name: string;
  is_dir: boolean;
  size: number | null;
  mtime: number;
};

type Result = {
  path: string;
  items: FileItem[];
  loading: boolean;
  error: string | null;
  navigate: (newPath: string) => void;
  refresh: () => void;
};

/**
 * Data layer for the agent file browser.
 *
 * Each navigate() bumps a key; the effect fires a /agent-files/list request
 * with an AbortController. If the caller navigates again before the previous
 * request completes, we abort the old one — that's how we avoid the
 * classic "old response overwrites new state" race that plagues the existing
 * FileManager.
 */
export function useFilesData(initialPath: string): Result {
  const [path, setPath] = useState(initialPath || "/root");
  const [items, setItems] = useState<FileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const desiredPathRef = useRef(path);
  desiredPathRef.current = path;

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  const navigate = useCallback((newPath: string) => {
    setPath(newPath);
  }, []);

  useEffect(() => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let alive = true;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const { data } = await api.get("/agent-files/list", {
          params: { path },
          signal: ctrl.signal,
        });
        // Defend against late responses that arrived after another navigate.
        if (!alive || desiredPathRef.current !== path) return;
        // Server may canonicalize the path (resolve symlinks); honor it.
        if (data.path && data.path !== path) {
          // Don't overwrite path if user navigated again; only if it's still our request.
          if (desiredPathRef.current === path) setPath(data.path);
        }
        setItems(data.items || []);
      } catch (e: any) {
        if (e?.name === "CanceledError" || e?.name === "AbortError" || ctrl.signal.aborted) {
          return;
        }
        if (alive) {
          setError(e?.response?.data?.detail || e?.message || "加载失败");
          setItems([]);
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();

    return () => {
      alive = false;
      ctrl.abort();
    };
  }, [path, tick]);

  return { path, items, loading, error, navigate, refresh };
}
