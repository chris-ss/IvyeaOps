export type ResearchMode = "keyword" | "asin";

export interface HistoryEntry {
  id: string;
  mode: ResearchMode;
  query: string;
  marketplace: string;
  provider: string;
  elapsed_s: number;
  ts: number;
  report: string;
}

export async function fetchHistory(): Promise<HistoryEntry[]> {
  const r = await fetch("/api/market/history", { credentials: "include" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function saveHistoryEntry(entry: HistoryEntry): Promise<void> {
  await fetch("/api/market/history", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ ...entry, elapsed_s: entry.elapsed_s }),
  });
}

export async function deleteHistoryEntry(id: string): Promise<void> {
  await fetch(`/api/market/history/${encodeURIComponent(id)}`, {
    method: "DELETE",
    credentials: "include",
  });
}

export async function clearHistory(): Promise<void> {
  await fetch("/api/market/history", { method: "DELETE", credentials: "include" });
}

export interface ResearchReq {
  mode: ResearchMode;
  query: string;
  marketplace: string;
  data_source?: string;   // "sorftime" | "sellersprite"
}

export type SseEvent =
  | { type: "phase"; phase: string }
  | { type: "progress"; step: string; done: number; total: number }
  | { type: "attempt"; provider: string }    // sent when a new provider is about to be tried
  | { type: "token"; text: string; provider: string }
  | { type: "warn"; detail: string }
  | { type: "error"; detail: string }
  | { type: "done"; provider: string; elapsed_s: number };

export function streamResearch(
  req: ResearchReq,
  onEvent: (evt: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return fetch("/api/market/research", {
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

export interface PulseResult {
  keyword: string;
  marketplace: string;
  detail: Record<string, any> | null;
  detail_error: string | null;
  trend: Record<string, any> | null;
  trend_error: string | null;
}

export async function fetchPulse(keyword: string, marketplace: string): Promise<PulseResult> {
  const r = await fetch("/api/market/pulse", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keyword, marketplace }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const data: PulseResult = await r.json();
  // Surface Sorftime API errors (e.g. expired key) instead of silent dashes
  if (!data.detail && data.detail_error) {
    const msg = data.detail_error.replace(/^keyword_detail:\s*/i, "");
    throw new Error(msg);
  }
  return data;
}
