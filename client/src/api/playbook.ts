export type PlaybookMode = "keyword" | "asin";

export interface HistoryEntry {
  id: string;
  mode: PlaybookMode;
  query: string;
  marketplace: string;
  price: string;
  cost: string;
  provider: string;
  data_source: string;
  elapsed_s: number;
  ts: number;
  report: string;
}

export async function fetchHistory(): Promise<HistoryEntry[]> {
  const r = await fetch("/api/playbook/history", { credentials: "include" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function saveHistoryEntry(entry: HistoryEntry): Promise<void> {
  await fetch("/api/playbook/history", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(entry),
  });
}

export async function deleteHistoryEntry(id: string): Promise<void> {
  await fetch(`/api/playbook/history/${encodeURIComponent(id)}`, {
    method: "DELETE",
    credentials: "include",
  });
}

export async function clearHistory(): Promise<void> {
  await fetch("/api/playbook/history", { method: "DELETE", credentials: "include" });
}

export interface PlaybookReq {
  mode: PlaybookMode;
  query: string;
  marketplace: string;
  price: string;
  cost: string;
  data_source: string;
}

export type SseEvent =
  | { type: "phase"; phase: string }
  | { type: "progress"; step: string; done: number; total: number }
  | { type: "attempt"; provider: string }
  | { type: "source"; requested: string; actual: string; label: string }
  | { type: "token"; text: string; provider: string }
  | { type: "warn"; detail: string }
  | { type: "error"; detail: string }
  | { type: "done"; provider: string; elapsed_s: number; data_source?: string; data_source_label?: string };

export function streamPlaybook(
  req: PlaybookReq,
  onEvent: (evt: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return fetch("/api/playbook/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(req),
    signal,
  }).then(async (resp) => {
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`HTTP ${resp.status}: ${text}`);
    }
    const reader = resp.body!.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const raw = line.slice(5).trim();
        try {
          onEvent(JSON.parse(raw) as SseEvent);
        } catch {
          // ignore malformed SSE
        }
      }
    }
  });
}
