import { useCallback, useEffect, useRef, useState } from "react";
import {
  commitChanges, discardFiles, getGitDiff, getGitStatus,
  stageFiles, unstageFiles,
  type GitDiff, type GitFile, type GitStatus,
} from "../../../../api/git";

type Result = {
  status: GitStatus | null;
  loadingStatus: boolean;
  selected: GitFile | null;
  select: (file: GitFile | null) => void;
  diff: GitDiff | null;
  loadingDiff: boolean;
  refresh: () => void;
  busyOp: boolean;
  err: string | null;
  clearErr: () => void;
  stage: (paths: string[]) => Promise<void>;
  unstage: (paths: string[]) => Promise<void>;
  discard: (paths: string[]) => Promise<void>;
  commit: (message: string) => Promise<boolean>;
};

/**
 * Single hook that owns the GitPanel's state machine:
 *   - status (refreshed on demand + after any mutation)
 *   - selected file → its diff (staged or unstaged depending on file state)
 *   - mutate ops (stage / unstage / discard / commit), all serialized
 *     via a single ``busyOp`` flag
 *
 * AbortControllers are used for both status and diff fetches so quick
 * project-switches don't race late responses.
 */
export function useGitController(projectId: string | null): Result {
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [tick, setTick] = useState(0);
  const [selected, setSelected] = useState<GitFile | null>(null);
  const [diff, setDiff] = useState<GitDiff | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const [busyOp, setBusyOp] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const statusAbortRef = useRef<AbortController | null>(null);
  const diffAbortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // Status fetcher
  useEffect(() => {
    if (!projectId) {
      setStatus(null);
      setSelected(null);
      setDiff(null);
      return;
    }
    statusAbortRef.current?.abort();
    const ctrl = new AbortController();
    statusAbortRef.current = ctrl;
    let alive = true;
    setLoadingStatus(true);
    setErr(null);
    getGitStatus(projectId, ctrl.signal)
      .then((s) => {
        if (!alive) return;
        setStatus(s);
        // If the previously-selected file disappeared (e.g. discarded),
        // clear selection so the diff pane resets.
        setSelected((prev) => {
          if (!prev) return prev;
          const still = s.files.find((f) => f.path === prev.path);
          return still || null;
        });
      })
      .catch((e: any) => {
        if (e?.name === "CanceledError" || e?.name === "AbortError" || ctrl.signal.aborted) return;
        if (alive) setErr(e?.response?.data?.detail || e?.message || "加载状态失败");
      })
      .finally(() => { if (alive) setLoadingStatus(false); });
    return () => { alive = false; ctrl.abort(); };
  }, [projectId, tick]);

  // Diff fetcher
  useEffect(() => {
    if (!projectId || !selected) {
      setDiff(null);
      return;
    }
    diffAbortRef.current?.abort();
    const ctrl = new AbortController();
    diffAbortRef.current = ctrl;
    let alive = true;
    setLoadingDiff(true);
    // For files that are both staged and unstaged, prefer the unstaged
    // (working-tree) diff — that's what the user is actively editing.
    const wantStaged = selected.staged && !selected.unstaged;
    getGitDiff(projectId, selected.path, wantStaged, ctrl.signal)
      .then((d) => { if (alive) setDiff(d); })
      .catch((e: any) => {
        if (e?.name === "CanceledError" || ctrl.signal.aborted) return;
        if (alive) setErr(e?.response?.data?.detail || e?.message || "加载 diff 失败");
      })
      .finally(() => { if (alive) setLoadingDiff(false); });
    return () => { alive = false; ctrl.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, selected?.path, selected?.staged, selected?.unstaged, tick]);

  const runOp = useCallback(async (fn: () => Promise<any>): Promise<boolean> => {
    if (busyOp || !projectId) return false;
    setBusyOp(true);
    setErr(null);
    try {
      await fn();
      refresh();
      return true;
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "git 操作失败");
      return false;
    } finally {
      setBusyOp(false);
    }
  }, [busyOp, projectId, refresh]);

  const stage = useCallback((paths: string[]) => {
    return runOp(() => stageFiles(projectId!, paths)).then(() => undefined);
  }, [projectId, runOp]);

  const unstage = useCallback((paths: string[]) => {
    return runOp(() => unstageFiles(projectId!, paths)).then(() => undefined);
  }, [projectId, runOp]);

  const discard = useCallback((paths: string[]) => {
    return runOp(() => discardFiles(projectId!, paths)).then(() => undefined);
  }, [projectId, runOp]);

  const commit = useCallback((message: string) => {
    return runOp(() => commitChanges(projectId!, message));
  }, [projectId, runOp]);

  return {
    status, loadingStatus,
    selected, select: setSelected,
    diff, loadingDiff,
    refresh, busyOp,
    err, clearErr: () => setErr(null),
    stage, unstage, discard, commit,
  };
}
