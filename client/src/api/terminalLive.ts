import { api } from "./client";

export type TerminalSessionStatus = "idle" | "live" | "closed" | "archived";

export type TerminalSession = {
  id: string;
  user_id: string;
  title: string;
  shell: string;
  workdir: string;
  status: TerminalSessionStatus;
  last_preview: string;
  created_at: string;
  updated_at: string;
  archived: boolean;
};

export type TerminalHistoryItem = {
  id: number;
  session_id: string;
  seq: number;
  stream: "input" | "output" | "system";
  content: string;
  created_at: string;
};

export type LegacyTtydStatus = {
  service: string;
  active: boolean;
  status: string;
  substate: string;
  url: string;
};

export async function listTerminalSessions(archived = false) {
  const { data } = await api.get<{ sessions: TerminalSession[] }>("/terminal/live/sessions", {
    params: { archived },
  });
  return data.sessions;
}

export async function createTerminalSession(payload?: {
  title?: string;
  shell?: string;
  workdir?: string;
}) {
  const { data } = await api.post<TerminalSession>("/terminal/live/sessions", payload || {});
  return data;
}

export async function updateTerminalSession(
  sessionId: string,
  payload: { title?: string; archived?: boolean; workdir?: string },
) {
  const { data } = await api.patch<TerminalSession>(`/terminal/live/sessions/${sessionId}`, payload);
  return data;
}

export async function closeTerminalSession(sessionId: string) {
  const { data } = await api.post<{ ok: boolean }>(`/terminal/live/sessions/${sessionId}/close`);
  return data;
}

export async function deleteTerminalSession(sessionId: string) {
  const { data } = await api.delete<{ ok: boolean }>(`/terminal/live/sessions/${sessionId}`);
  return data;
}

export async function getTerminalHistory(
  sessionId: string,
  options?: { limit?: number; afterSeq?: number; beforeSeq?: number },
) {
  const { data } = await api.get<{ items: TerminalHistoryItem[]; total: number }>(
    `/terminal/live/sessions/${sessionId}/history`,
    {
      params: {
        limit: options?.limit ?? 800,
        after_seq: options?.afterSeq ?? 0,
        before_seq: options?.beforeSeq,
      },
    },
  );
  return data;
}

export async function getLegacyTtydStatus() {
  const { data } = await api.get<LegacyTtydStatus>("/terminal/live/legacy-ttyd");
  return data;
}

export async function startLegacyTtyd() {
  const { data } = await api.post<LegacyTtydStatus>("/terminal/live/legacy-ttyd/start");
  return data;
}

export async function stopLegacyTtyd() {
  const { data } = await api.post<LegacyTtydStatus>("/terminal/live/legacy-ttyd/stop");
  return data;
}

// ─── Legacy snapshot API ────────────────────────────────────────────────────
// The legacy ttyd "main" tmux pane gets snapshotted on a fixed interval (and
// on demand) by the backend, with SHA1 dedup so idle terminals don't bloat
// the DB. Each snapshot is a sanitized tmux scrollback dump.

export type LegacySnapshot = {
  id: number;
  ts: string;
  title: string;
  source: "auto" | "manual" | "snap_curr" | "snap_prev" | "snap_before" | string;
  size: number;
  role?: SnapshotRole;
  label?: string;
};

export type LegacySnapshotFull = LegacySnapshot & { content: string };

export async function listLegacySnapshots(limit = 50, offset = 0) {
  const { data } = await api.get<{ sessions: LegacySnapshot[]; total: number }>(
    "/terminal/sessions",
    { params: { limit, offset } },
  );
  return data;
}

export async function getLegacySnapshot(id: number) {
  const { data } = await api.get<LegacySnapshotFull>(`/terminal/sessions/${id}`);
  return data;
}

export async function captureLegacySnapshot(title = "") {
  const { data } = await api.post<{ ok: boolean; id?: number; ts?: string; title?: string; skipped?: boolean; reason?: string; last_id?: number }>(
    "/terminal/capture",
    null,
    { params: title ? { title } : {} },
  );
  return data;
}

export async function deleteLegacySnapshot(id: number) {
  const { data } = await api.delete<{ ok: boolean }>(`/terminal/sessions/${id}`);
  return data;
}

export async function clearLegacySnapshots() {
  const { data } = await api.post<{ ok: boolean; removed: number }>(`/terminal/sessions/clear`);
  return data;
}

export async function searchLegacySnapshots(q: string, limit = 50) {
  const { data } = await api.get<{ sessions: (LegacySnapshot & { snippet: string })[]; query: string; total: number }>(
    "/terminal/search",
    { params: { q, limit } },
  );
  return data;
}

// ─── Live session snapshots ─────────────────────────────────────────────────
// Per-session periodic captures of the pyte screen content. Cascade-delete
// when the session is removed.

export type SnapshotRole = "snap_curr" | "snap_prev" | "snap_before";

export type LiveSnapshot = {
  id: number;       // terminal_history.id (primary key, used for delete)
  seq: number;
  ts: string;
  size: number;
  role?: SnapshotRole;
  label?: string;   // human label like "当前" / "上一个" / "之前"
};

export type LiveSnapshotFull = LiveSnapshot & { content: string };

export async function listLiveSnapshots(sessionId: string, limit = 80, offset = 0) {
  const { data } = await api.get<{ snapshots: LiveSnapshot[]; total: number }>(
    `/terminal/live/sessions/${sessionId}/snapshots`,
    { params: { limit, offset } },
  );
  return data;
}

export async function getLiveSnapshot(sessionId: string, snapId: number) {
  const { data } = await api.get<LiveSnapshotFull>(
    `/terminal/live/sessions/${sessionId}/snapshots/${snapId}`,
  );
  return data;
}

export async function captureLiveSnapshot(sessionId: string) {
  const { data } = await api.post<{ ok: boolean; id?: number; ts?: string; skipped?: boolean; reason?: string; error?: string }>(
    `/terminal/live/sessions/${sessionId}/snapshots`,
  );
  return data;
}

export async function deleteLiveSnapshot(sessionId: string, snapId: number) {
  const { data } = await api.delete<{ ok: boolean }>(
    `/terminal/live/sessions/${sessionId}/snapshots/${snapId}`,
  );
  return data;
}

export async function clearLiveSnapshots(sessionId: string) {
  const { data } = await api.post<{ ok: boolean; removed: number }>(
    `/terminal/live/sessions/${sessionId}/snapshots/clear`,
  );
  return data;
}

export function terminalWebSocketUrl(sessionId: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/terminal/live/${encodeURIComponent(sessionId)}/ws`;
}
