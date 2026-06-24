import { useEffect, useState } from "react";
import { MarkdownReport, relativeTime } from "../../../lib/reportFormat";

interface Entry {
  id: string;
  tool: string;
  title: string;
  query: string;
  country: string;
  provider: string;
  elapsed_s: number;
  ts: number;
  report: string;
}

export default function DeepHistory() {
  const [rows, setRows] = useState<Entry[]>([]);
  const [active, setActive] = useState<Entry | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    fetch("/api/deep-analysis/history", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => setRows(Array.isArray(d) ? d : []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const del = async (id: string) => {
    await fetch(`/api/deep-analysis/history/${encodeURIComponent(id)}`, {
      method: "DELETE",
      credentials: "include",
    });
    setActive(null);
    load();
  };

  if (active) {
    return (
      <div>
        <button className="tbtn" style={{ marginBottom: 12, fontSize: 11 }} onClick={() => setActive(null)}>
          ← 返回历史
        </button>
        <div style={{ fontSize: 11, color: "var(--t3)", marginBottom: 8 }}>
          {active.title} · {active.query} · {active.country} · {relativeTime(active.ts * 1000)}
        </div>
        <div className="market-report-body">
          <MarkdownReport text={active.report} />
        </div>
      </div>
    );
  }

  if (loading) return <div style={{ color: "var(--t3)", fontSize: 11 }}>加载中…</div>;
  if (rows.length === 0)
    return (
      <div style={{ color: "var(--t3)", fontSize: 11, lineHeight: 1.7 }}>
        暂无分析历史。在右下角 IvyeaAgent 里用自然语言说，例如「做一个 B0XXXX 的流量异动诊断」，
        生成的报告会保存到这里。
      </div>
    );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {rows.map((e) => (
        <div
          key={e.id}
          className="card"
          style={{ cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center" }}
          onClick={() => setActive(e)}
        >
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t)" }}>
              {e.title} · {e.query}
            </div>
            <div style={{ fontSize: 10, color: "var(--t3)" }}>
              {e.country} · {relativeTime(e.ts * 1000)} · {e.provider || "ivyea-agent"}
            </div>
          </div>
          <button
            className="tbtn"
            style={{ fontSize: 10 }}
            onClick={(ev) => {
              ev.stopPropagation();
              del(e.id);
            }}
          >
            删除
          </button>
        </div>
      ))}
    </div>
  );
}
