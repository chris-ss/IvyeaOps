import type { DataSourceId } from "../lib/dataSource";

export type WatchKind = "competitor" | "own";

export interface WatchItem {
  id: string;
  asin: string;
  marketplace: string;
  data_source?: DataSourceId;
  kind: WatchKind;
  label: string;
  ts: number;
}

export interface AsinPulse {
  asin: string;
  marketplace: string;
  error: string | null;
  title: string | null;
  brand: string | null;
  image: string | null;
  price: number | null;
  bsr: number | null;
  bsr_category: string | null;
  sub_rank: number | null;
  sub_category: string | null;
  est_sales: number | null;
  rating: number | null;
  review_count: number | null;
  variations: number | null;
  coupon: any | null;
  deal: any | null;
  inventory: number | null;
}

/** Numeric per-metric change (current − previous snapshot). */
export type PulseDelta = Partial<Record<
  "price" | "bsr" | "est_sales" | "rating" | "review_count" | "inventory",
  number
>>;

export interface PulseResult {
  current: AsinPulse;
  delta: PulseDelta;
  prev_ts: number | null;
}

export interface AlertItem {
  asin: string;
  marketplace: string;
  kind: WatchKind;
  label: string;
  metric: string;
  from: number | boolean | null;
  to: number | boolean | null;
  diff: number | null;
  ts: number;
}

export async function listWatch(dataSource: DataSourceId = "sorftime"): Promise<WatchItem[]> {
  const r = await fetch(`/api/home/watch?data_source=${encodeURIComponent(dataSource)}`, { credentials: "include" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function addWatch(item: {
  asin: string; marketplace: string; data_source: DataSourceId; kind: WatchKind; label?: string;
}): Promise<{ id: string }> {
  const r = await fetch("/api/home/watch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(item),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function deleteWatch(id: string): Promise<void> {
  await fetch(`/api/home/watch/${encodeURIComponent(id)}`, {
    method: "DELETE",
    credentials: "include",
  });
}

export interface WatchSnapshot {
  id: string;
  asin: string;
  marketplace: string;
  data_source?: DataSourceId;
  kind: WatchKind;
  label: string;
  ts: number | null;
  metrics: Record<string, any>;
}

/** Latest stored snapshot per watched ASIN — NO Sorftime call (cache-first). */
export async function fetchWatchSnapshots(dataSource: DataSourceId = "sorftime"): Promise<WatchSnapshot[]> {
  const r = await fetch(`/api/home/watch-snapshots?data_source=${encodeURIComponent(dataSource)}`, { credentials: "include" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function pulseAsin(asin: string, marketplace: string, dataSource: DataSourceId = "sorftime"): Promise<PulseResult> {
  const r = await fetch("/api/home/pulse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ asin, marketplace, data_source: dataSource }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function fetchAlerts(dataSource: DataSourceId = "sorftime"): Promise<AlertItem[]> {
  const r = await fetch(`/api/home/alerts?data_source=${encodeURIComponent(dataSource)}`, { credentials: "include" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ── Category dashboard ────────────────────────────────────────────────────────

export interface CategoryProduct {
  rank: number;
  asin: string;
  title: string | null;
  brand: string | null;
  price: number | null;
  bsr: number | null;
  est_sales: number | null;
  rating: number | null;
  review_count: number | null;
}

export interface CategoryBand {
  label: string;
  min: number;
  max: number;
  count: number;
  sales: number | null;
}

export interface CategorySummary {
  count: number;
  avg_price: number | null;
  total_sales: number | null;
}

export interface CategoryChanges {
  new_entrants: string[];
  movers: { asin: string; from: number; to: number; diff: number }[];
  has_baseline: boolean;
}

export interface CategoryResult {
  query: string;
  marketplace: string;
  mode: string;                       // "category" | "keyword"
  node_id: string;
  category_name: string | null;       // resolved category (for verification)
  source: string;                     // "nodeId" | "asin" | "name" | "keyword"
  data_source?: DataSourceId;
  summary_kind?: string;
  error: string | null;
  summary: CategorySummary | null;
  bands: CategoryBand[];
  top: CategoryProduct[];
  changes: CategoryChanges;
}

/** Last cached category analysis — NO Sorftime call. */
export async function fetchCategoryCached(query: string, marketplace: string, mode = "category", dataSource: DataSourceId = "sorftime"): Promise<{ cached: CategoryResult | null; ts: number | null }> {
  const r = await fetch(`/api/home/category-result?query=${encodeURIComponent(query)}&marketplace=${encodeURIComponent(marketplace)}&mode=${mode}&data_source=${encodeURIComponent(dataSource)}`, {
    credentials: "include",
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function fetchCategory(query: string, marketplace: string, mode = "category", dataSource: DataSourceId = "sorftime"): Promise<CategoryResult> {
  const r = await fetch("/api/home/category", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ query, marketplace, mode, data_source: dataSource }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ── Market (大盘) traffic ─────────────────────────────────────────────────────

export interface MarketWatchItem {
  id: string;
  query: string;
  marketplace: string;
  data_source?: DataSourceId;
  label: string;
  ts: number;
}

export interface MarketPoint {
  day: string;
  search_volume: number | null;
  total_sales: number | null;
  avg_price: number | null;
}

export interface SeriesPoint { day: string; value: number }

export interface MarketSeries {
  query: string;
  marketplace: string;
  data_source?: DataSourceId;
  market: MarketPoint[];
  own: SeriesPoint[];
  competitor: SeriesPoint[];
}

export async function listMarketWatch(dataSource: DataSourceId = "sorftime"): Promise<MarketWatchItem[]> {
  const r = await fetch(`/api/home/market-watch?data_source=${encodeURIComponent(dataSource)}`, { credentials: "include" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function addMarketWatch(item: { query: string; marketplace: string; data_source: DataSourceId; label?: string }): Promise<{ id: string }> {
  const r = await fetch("/api/home/market-watch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(item),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function deleteMarketWatch(id: string): Promise<void> {
  await fetch(`/api/home/market-watch/${encodeURIComponent(id)}`, {
    method: "DELETE",
    credentials: "include",
  });
}

export async function fetchMarketSeries(query: string, marketplace: string, dataSource: DataSourceId = "sorftime"): Promise<MarketSeries> {
  const r = await fetch(`/api/home/market-series?query=${encodeURIComponent(query)}&marketplace=${encodeURIComponent(marketplace)}&data_source=${encodeURIComponent(dataSource)}`, {
    credentials: "include",
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function recordMarketNow(dataSource: DataSourceId = "sorftime"): Promise<{ day: string; recorded_market: number; recorded_asin: number }> {
  const r = await fetch(`/api/home/market-record?data_source=${encodeURIComponent(dataSource)}`, { method: "POST", credentials: "include" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function marketDailyBackfill(query: string, marketplace: string, category: string, days = 31, dataSource: DataSourceId = "sorftime"): Promise<{
  error: string | null; filled: number; node_id: string; category_name: string | null; days?: number;
}> {
  const r = await fetch("/api/home/market-daily-backfill", {
    method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
    body: JSON.stringify({ query, marketplace, category, days, data_source: dataSource }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function backfillMarket(query: string, marketplace: string, dataSource: DataSourceId = "sorftime"): Promise<{
  market_points: number; asin_points: number; asin_errors: number; sv_error: string | null;
}> {
  const r = await fetch("/api/home/market-backfill", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ query, marketplace, data_source: dataSource }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ── Keyword watchlist (server-side, cache-first) ──────────────────────────────

export interface KeywordData {
  keyword: string;
  marketplace: string;
  data_source?: DataSourceId;
  detail: Record<string, any> | null;
  detail_error: string | null;
  trend: Record<string, any> | null;
  trend_error: string | null;
}

export interface KeywordItem {
  id: string;
  keyword: string;
  marketplace: string;
  data_source?: DataSourceId;
  label: string;
  ts: number;
  data: KeywordData | null;
  data_ts: number | null;
}

export async function listKeywords(dataSource: DataSourceId = "sorftime"): Promise<KeywordItem[]> {
  const r = await fetch(`/api/home/keywords?data_source=${encodeURIComponent(dataSource)}`, { credentials: "include" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function addKeyword(keyword: string, marketplace: string, dataSource: DataSourceId = "sorftime"): Promise<{ id: string }> {
  const r = await fetch("/api/home/keyword", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ keyword, marketplace, data_source: dataSource }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function deleteKeyword(id: string): Promise<void> {
  await fetch(`/api/home/keyword/${encodeURIComponent(id)}`, { method: "DELETE", credentials: "include" });
}

// ── Expanded keywords (拓展词) ────────────────────────────────────────────────

export interface KeywordExtendItem {
  keyword: string;
  monthly_search: number | null;
  cpc: number | null;
  seasonality: string | null;
  score: number;
  related: boolean;
  evidence_sales: number | null;
}

export async function fetchKeywordExtendsCached(keyword: string, marketplace: string, dataSource: DataSourceId = "sorftime"): Promise<{ items: KeywordExtendItem[]; ts: number | null }> {
  const r = await fetch(`/api/home/keyword-extends?keyword=${encodeURIComponent(keyword)}&marketplace=${encodeURIComponent(marketplace)}&data_source=${encodeURIComponent(dataSource)}`, { credentials: "include" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function pulseKeywordExtends(keyword: string, marketplace: string, dataSource: DataSourceId = "sorftime"): Promise<{ items: KeywordExtendItem[]; ts: number | null; error: string | null }> {
  const r = await fetch("/api/home/keyword-extends", {
    method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
    body: JSON.stringify({ keyword, marketplace, data_source: dataSource }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function deepKeywordExtendSales(keyword: string, marketplace: string, dataSource: DataSourceId = "sorftime"): Promise<{ items: KeywordExtendItem[]; ts: number | null }> {
  const r = await fetch("/api/home/keyword-extends-sales", {
    method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
    body: JSON.stringify({ keyword, marketplace, data_source: dataSource }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function pulseKeyword(keyword: string, marketplace: string, dataSource: DataSourceId = "sorftime"): Promise<KeywordData> {
  const r = await fetch("/api/home/keyword-pulse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ keyword, marketplace, data_source: dataSource }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const data: KeywordData = await r.json();
  if (!data.detail && data.detail_error) {
    throw new Error(data.detail_error.replace(/^keyword_detail:\s*/i, ""));
  }
  return data;
}
