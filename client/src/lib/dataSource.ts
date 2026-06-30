// Shared market-data source selection, used by 首页 / 市场调研 / 打法推荐.
// Availability is surface-specific so unsupported providers can never fall
// through to a different backend silently.

export type DataSourceId = "sorftime" | "sif" | "sellersprite";
export type DataSourceSurface = "market" | "playbook" | "home";

export type DataSourceMeta = {
  id: DataSourceId;
  name: string;
  ready: boolean;
  note?: string;
  surfaces: DataSourceSurface[];
};

export const DATA_SOURCES: DataSourceMeta[] = [
  { id: "sorftime", name: "Sorftime", ready: true, surfaces: ["market", "playbook", "home"] },
  { id: "sellersprite", name: "卖家精灵", ready: true, surfaces: ["market", "playbook", "home"] },
  { id: "sif", name: "SIF", ready: false, surfaces: [], note: "即将支持" },
];

const KEY = "ivyea-ops-data-source";

export function getDataSource(): DataSourceId {
  const v = (typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null) as DataSourceId | null;
  return v && DATA_SOURCES.some((s) => s.id === v) ? v : "sorftime";
}

export function setDataSource(id: DataSourceId): void {
  localStorage.setItem(KEY, id);
}

export function dataSourceMeta(id: DataSourceId, surface?: DataSourceSurface): DataSourceMeta {
  const source = DATA_SOURCES.find((s) => s.id === id) ?? DATA_SOURCES[0];
  if (!surface) return source;
  const ready = source.ready && source.surfaces.includes(surface);
  return {
    ...source,
    ready,
    note: source.note,
  };
}
