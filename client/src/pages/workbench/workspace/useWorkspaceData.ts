import { useCallback, useEffect, useRef, useState } from "react";
import {
  listProjects,
  listProjectSessions,
  refreshProjects,
  type Project,
  type ProjectSession,
} from "../../../api/projects";

type Result = {
  projects: Project[];
  loadingProjects: boolean;
  refresh: () => Promise<void>;
  /** Sessions cached per project so we can show counts without a request per row. */
  getSessions: (projectId: string) => ProjectSession[] | undefined;
  loadSessions: (projectId: string) => Promise<ProjectSession[]>;
  loadingSessionsFor: Record<string, boolean>;
};

/**
 * Workspace data layer:
 *   - top-level project list (auto-refreshed on mount)
 *   - lazy per-project session list (loaded when the user expands a project)
 *
 * Sessions stay cached so collapsing → re-expanding doesn't refetch. A
 * manual refresh() invalidates both layers.
 */
export function useWorkspaceData(): Result {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [sessionsByProject, setSessionsByProject] = useState<Record<string, ProjectSession[]>>({});
  const [loadingSessionsFor, setLoadingSessionsFor] = useState<Record<string, boolean>>({});

  const aliveRef = useRef(true);
  useEffect(() => () => { aliveRef.current = false; }, []);

  const loadProjects = useCallback(async () => {
    setLoadingProjects(true);
    try {
      const list = await listProjects();
      if (aliveRef.current) setProjects(list);
    } catch {
      // surface as empty list; sidebar shows empty-state
      if (aliveRef.current) setProjects([]);
    } finally {
      if (aliveRef.current) setLoadingProjects(false);
    }
  }, []);

  useEffect(() => { void loadProjects(); }, [loadProjects]);

  const loadSessions = useCallback(async (projectId: string) => {
    setLoadingSessionsFor((m) => ({ ...m, [projectId]: true }));
    try {
      const { sessions } = await listProjectSessions(projectId);
      if (aliveRef.current) {
        setSessionsByProject((m) => ({ ...m, [projectId]: sessions }));
      }
      return sessions;
    } catch {
      if (aliveRef.current) {
        setSessionsByProject((m) => ({ ...m, [projectId]: [] }));
      }
      return [] as ProjectSession[];
    } finally {
      if (aliveRef.current) {
        setLoadingSessionsFor((m) => ({ ...m, [projectId]: false }));
      }
    }
  }, []);

  const refresh = useCallback(async () => {
    try { await refreshProjects(); } catch { /* ignore */ }
    setSessionsByProject({});
    await loadProjects();
  }, [loadProjects]);

  const getSessions = useCallback((projectId: string) => sessionsByProject[projectId], [sessionsByProject]);

  return { projects, loadingProjects, refresh, getSessions, loadSessions, loadingSessionsFor };
}
