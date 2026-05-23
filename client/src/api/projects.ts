// Projects = aggregated view of "workspaces" — directories where AI sessions
// were run. Derived server-side from agent_sessions + Claude/Codex jsonl logs.
import { api } from "./client";

export type ProjectSource = "hub" | "claude" | "codex";

export interface Project {
  id: string;
  name: string;
  path: string;
  sources: Record<ProjectSource, boolean>;
  session_count: number;
  last_active: number;        // unix seconds
  last_active_iso: string;    // local YYYY-MM-DDTHH:mm:ss
}

export interface ProjectSession {
  id: string;
  source: ProjectSource;
  title: string;
  agent: string | null;
  last_active: number;
  last_active_iso: string;
  workdir: string;
}

export async function listProjects(): Promise<Project[]> {
  const { data } = await api.get<{ projects: Project[]; total: number }>("/projects");
  return data.projects;
}

export async function getProject(projectId: string): Promise<Project> {
  const { data } = await api.get<Project>(`/projects/${projectId}`);
  return data;
}

export async function listProjectSessions(projectId: string): Promise<{
  project: Project;
  sessions: ProjectSession[];
}> {
  const { data } = await api.get<{ project: Project; sessions: ProjectSession[]; total: number }>(
    `/projects/${projectId}/sessions`,
  );
  return { project: data.project, sessions: data.sessions };
}

export async function refreshProjects(): Promise<void> {
  await api.post("/projects/refresh");
}

// ─── Transcript (read-only view of external claude/codex sessions) ─────────

export type TranscriptMessageKind = "text" | "system" | "tool_call" | "tool_result";

export interface TranscriptMessage {
  role: "user" | "assistant" | "system";
  text: string;
  ts: string | null;
  kind: TranscriptMessageKind;
}

export async function getSessionTranscript(projectId: string, sessionId: string): Promise<{
  project: Project;
  session: ProjectSession;
  messages: TranscriptMessage[];
}> {
  const { data } = await api.get<{
    project: Project; session: ProjectSession;
    messages: TranscriptMessage[]; total: number;
  }>(`/projects/${projectId}/sessions/${sessionId}/transcript`);
  return data;
}

// ─── Resume external session into a new hub agent_session ──────────────────

export interface ResumeResponse {
  ok: boolean;
  session_id: string;      // new hub agent_session id
  project_id: string;
  resume_target: string;   // "<source>:<orig_id>"
}

export async function resumeExternalSession(
  projectId: string,
  sessionId: string,
  body?: { title?: string; model?: string },
): Promise<ResumeResponse> {
  const { data } = await api.post<ResumeResponse>(
    `/projects/${projectId}/sessions/${sessionId}/resume`,
    body || {},
  );
  return data;
}
