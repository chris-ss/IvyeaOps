export type ResearchMode = "keyword" | "asin";

export interface ResearchReq {
  mode: ResearchMode;
  query: string;
  marketplace: string;
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
