// Git operations scoped to a workspace project. Endpoints live under
// /api/git/* on the backend (see server/app/routers/git.py). All mutate
// operations take the projectId so we never trust a raw path from the
// browser.
import { api } from "./client";

export interface GitFile {
  path: string;
  status: string;
  label: string;
  staged: boolean;
  unstaged: boolean;
  xy?: string;
  from?: string;        // present for renames
}

export interface GitStatus {
  is_repo: boolean;
  path: string;
  error: string | null;
  branch: string | null;
  ahead: number;
  behind: number;
  files: GitFile[];
}

export interface GitDiff {
  file: string;
  staged: boolean;
  diff: string;
  truncated: boolean;
}

export interface GitCommit {
  sha: string;
  author: string;
  when: string;
  subject: string;
}

export async function getGitStatus(projectId: string, signal?: AbortSignal): Promise<GitStatus> {
  const { data } = await api.get<GitStatus>("/git/status", { params: { project_id: projectId }, signal });
  return data;
}

export async function getGitDiff(
  projectId: string, file: string, staged: boolean = false, signal?: AbortSignal,
): Promise<GitDiff> {
  const { data } = await api.get<GitDiff>("/git/diff", {
    params: { project_id: projectId, file, staged },
    signal,
  });
  return data;
}

export async function stageFiles(projectId: string, paths: string[]): Promise<void> {
  await api.post("/git/stage", { project_id: projectId, paths });
}

export async function unstageFiles(projectId: string, paths: string[]): Promise<void> {
  await api.post("/git/unstage", { project_id: projectId, paths });
}

export async function discardFiles(projectId: string, paths: string[]): Promise<void> {
  await api.post("/git/discard", { project_id: projectId, paths });
}

export async function commitChanges(projectId: string, message: string): Promise<{ ok: boolean; sha: string; message: string }> {
  const { data } = await api.post("/git/commit", { project_id: projectId, message });
  return data;
}

export async function getGitLog(projectId: string, limit: number = 20): Promise<GitCommit[]> {
  const { data } = await api.get<{ commits: GitCommit[] }>("/git/log", {
    params: { project_id: projectId, limit },
  });
  return data.commits;
}
