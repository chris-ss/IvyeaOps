import { useEffect, useState } from "react";
import { fetchAlerts, type AlertItem } from "../../../api/home";
import type { DataSourceId } from "../../../lib/dataSource";

const METRIC_LABEL: Record<string, string> = {
  price: "价格", bsr: "BSR", est_sales: "月销", rating: "评分",
  review_count: "评论", inventory: "库存", coupon: "Coupon", deal: "活动",
};

function fmtNum(v: number | boolean | null, metric: string): string {
  if (typeof v === "boolean") return v ? "有" : "无";
  if (v == null) return "—";
  if (metric === "price") return "$" + v.toFixed(2);
  if (metric === "bsr") return "#" + Math.round(v);
  if (v >= 1000) return (v / 1000).toFixed(1) + "K";
  return String(Math.round(v));
}

function describe(a: AlertItem): { text: string; up: boolean } {
  const label = METRIC_LABEL[a.metric] ?? a.metric;
  if (a.metric === "coupon" || a.metric === "deal") {
    const on = a.to === true;
    return { text: `${label}${on ? "上线" : "下线"}`, up: on };
  }
  const up = typeof a.diff === "number" ? a.diff > 0 : false;
  return {
    text: `${label} ${fmtNum(a.from, a.metric)}→${fmtNum(a.to, a.metric)}`,
    up,
  };
}

export default function AlertStrip({ reloadKey, dataSource, marketplace, onJump }: {
  reloadKey: number;
  dataSource: DataSourceId;
  marketplace: string;
  onJump?: (kind: "competitor" | "own", marketplace: string) => void;
}) {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetchAlerts(dataSource)
      .then(setAlerts)
      .catch(() => setAlerts([]))
      .finally(() => setLoaded(true));
  }, [reloadKey, dataSource]);

  if (!loaded) return null;

  if (alerts.length === 0) {
    return (
      <div className="home-alerts home-alerts-empty">
        <span className="home-alerts-icon">◔</span>
        暂无异动 · 监控的 ASIN 积累两次以上快照后，这里会汇总价格 / 排名 / 活动等变化
      </div>
    );
  }

  return (
    <div className="home-alerts">
      <span className="home-alerts-icon">⚡</span>
      <div className="home-alerts-track">
        {alerts.map((a, i) => {
          const { text, up } = describe(a);
          return (
            <button
              key={i}
              className={"home-alert-chip " + (up ? "up" : "down")}
              title={`${a.label || a.asin} · ${a.marketplace}`}
              onClick={() => onJump?.(a.kind, a.marketplace)}
            >
              <span className="home-alert-asin">
                {a.kind === "own" ? "★" : ""}{a.label || a.asin}
                {a.marketplace !== marketplace && <span className="home-alert-mkt">{a.marketplace}</span>}
              </span>
              <span className="home-alert-dir">{up ? "▲" : "▼"}</span>
              <span className="home-alert-text">{text}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
