// Shared market-data source selection, used by 首页 / 市场调研 / 打法推荐.
//
// Only Sorftime is wired to a real backend today; SIF and 卖家精灵 are shown as
// "即将支持" placeholders (they have config slots in 系统配置 but no data client
// yet). Boards read `getDataSource()` to decide whether to fetch or show the
// placeholder, and re-fetch when it changes. Promote to a backend hub_settings
// key once the other clients land.

export type DataSourceId = "sorftime" | "sif" | "sellersprite";

export type DataSourceMeta = {
  id: DataSourceId;
  name: string;
  ready: boolean;
  note?: string;
};

export const DATA_SOURCES: DataSourceMeta[] = [
  { id: "sorftime", name: "Sorftime", ready: true },
  { id: "sellersprite", name: "卖家精灵", ready: true, note: "需在系统配置填卖家精灵 Key" },
  { id: "sif", name: "SIF", ready: false, note: "即将支持" },
];

const KEY = "ivyea-ops-data-source";

export function getDataSource(): DataSourceId {
  const v = (typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null) as DataSourceId | null;
  return v && DATA_SOURCES.some((s) => s.id === v) ? v : "sorftime";
}

export function setDataSource(id: DataSourceId): void {
  localStorage.setItem(KEY, id);
}

export function dataSourceMeta(id: DataSourceId): DataSourceMeta {
  return DATA_SOURCES.find((s) => s.id === id) ?? DATA_SOURCES[0];
}
