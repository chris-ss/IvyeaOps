// API client for the multi-agent hub.
//
// Endpoint surface mirrors /api/agent-* on the FastAPI backend; see
// app/routers/agent_hub.py.  Streaming endpoints (SSE chat / WS CLI) are
// handled by their respective components — they don't go through axios.
import { api } from "./client";

export type AgentInfo = {
  id: string;
  display_name: string;
  binary_path: string;
  default_model: string | null;
  models: string[];
  caps: Record<string, any>;
  enabled: boolean;
};

export type AgentSession = {
  id: string;
  user_id: string;
  parent_id: string | null;
  branch_anchor_seq: number | null;
  agent_id: string;
  model: string | null;
  title: string;
  workdir: string | null;
  status: string;
  last_summary_id: string | null;
  last_preview: string;
  token_estimate: number;
  created_at: string;
  updated_at: string;
  archived: boolean;
  // populated by GET /agent-sessions/:id
  children?: AgentSession[];
  live?: boolean;
};

export type AgentMessage = {
  id: string;
  session_id: string;
  seq: number;
  role: "user" | "assistant" | "system";
  kind: "text" | "tool_call" | "tool_result" | "summary" | "cli_frame" | "error";
  source: "chat" | "cli" | "system";
  content: string;
  meta: Record<string, any>;
  created_at: string;
  inherited?: boolean;
};

// --- Agents ---------------------------------------------------------------
export async function fetchAgents(): Promise<AgentInfo[]> {
  const { data } = await api.get<{ agents: AgentInfo[] }>("/agents");
  return data.agents;
}

export async function rediscoverAgents(): Promise<AgentInfo[]> {
  const { data } = await api.post<{ agents: AgentInfo[] }>("/agents/rediscover");
  return data.agents;
}

// --- Sessions -------------------------------------------------------------
export async function listSessions(opts?: { archived?: boolean }): Promise<AgentSession[]> {
  const { data } = await api.get<{ sessions: AgentSession[] }>("/agent-sessions", {
    params: { archived: opts?.archived ? true : false },
  });
  return data.sessions;
}

export async function createSession(body: {
  agent_id: string;
  model?: string;
  title?: string;
  workdir?: string;
}): Promise<AgentSession> {
  const { data } = await api.post<AgentSession>("/agent-sessions", body);
  return data;
}

export async function getSession(sid: string): Promise<AgentSession> {
  const { data } = await api.get<AgentSession>(`/agent-sessions/${sid}`);
  return data;
}

export async function updateSession(
  sid: string,
  body: { title?: string; archived?: boolean; model?: string },
): Promise<AgentSession> {
  const { data } = await api.patch<AgentSession>(`/agent-sessions/${sid}`, body);
  return data;
}

export async function deleteSession(sid: string): Promise<void> {
  await api.delete(`/agent-sessions/${sid}`);
}

export async function listMessages(
  sid: string,
  opts?: { afterSeq?: number; includeCli?: boolean; includeInherited?: boolean },
): Promise<{ messages: AgentMessage[]; live: boolean }> {
  const { data } = await api.get<{ messages: AgentMessage[]; live: boolean }>(
    `/agent-sessions/${sid}/messages`,
    {
      params: {
        after_seq: opts?.afterSeq ?? 0,
        include_cli: opts?.includeCli ?? true,
        include_inherited: opts?.includeInherited ?? true,
      },
    },
  );
  return data;
}

export async function branchSession(
  sid: string,
  body: { anchor_seq: number; title?: string },
): Promise<AgentSession> {
  const { data } = await api.post<AgentSession>(`/agent-sessions/${sid}/branch`, body);
  return data;
}

export async function compactSession(sid: string): Promise<{ id: string; content: string }> {
  const { data } = await api.post(`/agent-sessions/${sid}/compact`);
  return data;
}

export async function stopSessionPty(sid: string): Promise<void> {
  await api.post(`/agent-sessions/${sid}/stop`);
}

// --- Chat (SSE) -----------------------------------------------------------
//
// We hand-roll an SSE consumer because EventSource cannot send POST bodies.
// The browser fetch() with a streamed body is simpler than a service worker.
export type ChatEvent =
  | { type: "user_message"; payload: AgentMessage }
  | { type: "token"; payload: { text: string } }
  | { type: "assistant_message"; payload: AgentMessage }
  | { type: "exit"; payload: { code: number | null } }
  | { type: "warning"; payload: { detail: string } }
  | { type: "error"; payload: { detail: string } }
  | { type: "auto_compacted"; payload: { summary_id: string } }
  | { type: "done"; payload: { ok: true } };

export async function* sendChat(
  sid: string,
  content: string,
  opts?: { resetPty?: boolean; signal?: AbortSignal },
): AsyncGenerator<ChatEvent, void, void> {
  const resp = await fetch(`/api/agent-chat/sessions/${sid}/messages`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ content, reset_pty: opts?.resetPty ?? false }),
    signal: opts?.signal,
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const j = await resp.json();
      detail = j.detail || detail;
    } catch {
      // leave as is
    }
    throw new Error(detail);
  }
  if (!resp.body) {
    throw new Error("响应没有 body");
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    // SSE blocks separated by \n\n.
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const lines = block.split("\n");
      let event = "message";
      const data: string[] = [];
      for (const line of lines) {
        if (line.startsWith("event:")) {
          event = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          data.push(line.slice(5).trim());
        }
      }
      const dataStr = data.join("\n");
      let payload: any = dataStr;
      try {
        payload = JSON.parse(dataStr);
      } catch {
        // keep raw string
      }
      yield { type: event as any, payload };
    }
  }
}

// --- CLI WebSocket --------------------------------------------------------
export function cliWebSocketUrl(sid: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/agent-cli/${encodeURIComponent(sid)}/ws`;
}
