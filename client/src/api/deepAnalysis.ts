/* Deep Analysis API client */
import { api } from "./client";

export interface KeywordReq {
  keyword: string;
  country?: string;
  asin?: string;
}

export interface CompetitorReq {
  asin: string;
  country?: string;
  time_type?: string;
  time_value?: string;
}

export interface TrafficReq {
  asin: string;
  country?: string;
}

export interface ReviewsReq {
  asin: string;
  country?: string;
}

export interface ListingRewriteReq {
  asins: string[];
  marketplace?: string;
  fields?: string[];
  style?: string;
}

export async function keywordCompetition(req: KeywordReq, signal?: AbortSignal) {
  const { data } = await api.post("/deep-analysis/keyword", req, { signal });
  return data;
}

export async function competitorLookup(req: CompetitorReq, signal?: AbortSignal) {
  const { data } = await api.post("/deep-analysis/competitor", req, { signal });
  return data;
}

export async function trafficDiagnosis(req: TrafficReq, signal?: AbortSignal) {
  const { data } = await api.post("/deep-analysis/traffic", req, { signal });
  return data;
}

/* SSE streaming for reviews and listing-rewrite */
export type SseEvent =
  | { type: "phase"; phase: string }
  | { type: "attempt"; provider: string }
  | { type: "token"; text: string; provider: string }
  | { type: "error"; detail: string }
  | { type: "done"; provider: string; elapsed_s: number };

export function streamReviews(
  req: ReviewsReq,
  onEvent: (evt: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return fetch("/api/deep-analysis/reviews", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(req),
    signal,
  }).then((resp) => {
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return consumeSSE(resp, onEvent);
  });
}

export function streamListingRewrite(
  req: ListingRewriteReq,
  onEvent: (evt: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return fetch("/api/deep-analysis/listing-rewrite", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(req),
    signal,
  }).then((resp) => {
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return consumeSSE(resp, onEvent);
  });
}

export async function consumeSSE(
  resp: Response,
  onEvent: (evt: SseEvent) => void,
): Promise<void> {
  const reader = resp.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith(":")) continue;
      if (trimmed.startsWith("data:")) {
        try {
          const evt = JSON.parse(trimmed.slice(5).trim());
          onEvent(evt);
        } catch { /* ignore */ }
      }
    }
  }
}
