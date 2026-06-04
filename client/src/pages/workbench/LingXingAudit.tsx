import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";

function Btn({ onClick, children }: any) {
  return <button onClick={onClick} style={{ background: "var(--bg2)", color: "var(--t)", border: "1px solid var(--b)", borderRadius: 4, padding: "5px 12px", fontSize: 11, cursor: "pointer" }}>{children}</button>;
}

const STATUS_COLOR: Record<string, string> = {
  ok: "var(--acc)", denied: "var(--t3)", blocked: "var(--red)", error: "var(--red)",
};

export default function LingXingAudit() {
  const [rows, setRows] = useState<any[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [msg, setMsg] = useState("");

  useEffect(() => { void load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, []);
  async function load() {
    try { setRows((await api.get("/lingxing/audit?limit=300")).data.rows || []); }
    catch (e: any) { setMsg(e?.response?.data?.detail || e?.message || "加载失败"); }
  }

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of rows) c[r.status] = (c[r.status] || 0) + 1;
    return c;
  }, [rows]);
  const shown = filter ? rows.filter((r) => r.status === filter) : rows;

  return (
    <div>
      <div className="card" style={{ padding: 12, marginBottom: 10, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: "var(--t3)" }}>全部调用审计（读/写/探针）</span>
        {["ok", "denied", "blocked", "error"].map((s) => (
          <span key={s} onClick={() => setFilter(filter === s ? "" : s)} style={{
            fontSize: 11, cursor: "pointer", padding: "2px 8px", borderRadius: 10,
            background: filter === s ? "var(--bg2)" : "transparent", border: "1px solid var(--b)",
            color: STATUS_COLOR[s] || "var(--t2)",
          }}>{s} {counts[s] || 0}</span>
        ))}
        <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {filter && <span style={{ fontSize: 10, color: "var(--t3)" }}>筛选: {filter}（点击取消）</span>}
          <Btn onClick={load}>刷新</Btn>
        </span>
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        {shown.length === 0 ? (
          <div style={{ padding: 30, textAlign: "center", color: "var(--t3)", fontSize: 11 }}>{msg || "暂无审计记录"}</div>
        ) : (
          <table className="lx-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
            <thead><tr>{["时间", "调用方", "工具/路由", "类型", "状态", "耗时", "详情"].map((h) => (
              <th key={h} style={{ textAlign: "left", padding: "7px 10px", color: "var(--t3)", borderBottom: "1px solid var(--b)", whiteSpace: "nowrap" }}>{h}</th>))}</tr></thead>
            <tbody>
              {shown.map((r, i) => (
                <tr key={i} style={{ borderBottom: "1px solid var(--b)" }}>
                  <td style={td}>{fmtTs(r.ts)}</td>
                  <td style={td}>{r.caller}</td>
                  <td style={{ ...td, maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis" }}>{r.tool}</td>
                  <td style={td}>{r.kind}</td>
                  <td style={{ ...td, color: STATUS_COLOR[r.status] || "var(--t2)", fontWeight: 600 }}>{r.status}</td>
                  <td style={td}>{r.latency_ms ? `${r.latency_ms}ms` : "—"}</td>
                  <td style={{ ...td, maxWidth: 280, whiteSpace: "normal", color: "var(--t3)" }}>{r.detail || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

const td: React.CSSProperties = { padding: "6px 10px", color: "var(--t2)", whiteSpace: "nowrap", verticalAlign: "top" };
function fmtTs(ts?: string) { if (!ts) return "—"; try { return new Date(ts).toLocaleString("zh-CN", { hour12: false }); } catch { return ts; } }
