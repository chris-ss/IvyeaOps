import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { sidCurrencyMap, fmtBudget, type Cur } from "./lingxingCurrency";

const inputStyle: React.CSSProperties = {
  background: "var(--bg1)", border: "1px solid var(--b)", borderRadius: 3,
  padding: "5px 7px", fontSize: 11, color: "var(--t)", outline: "none",
  fontFamily: "inherit", boxSizing: "border-box",
};
function Btn({ onClick, children, primary, disabled }: any) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      background: primary ? "var(--acc)" : "var(--bg2)", color: primary ? "#000" : "var(--t)",
      border: primary ? "none" : "1px solid var(--b)", borderRadius: 4, padding: "5px 12px",
      fontSize: 11, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.55 : 1,
    }}>{children}</button>
  );
}

const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

export default function LingXingAutomation() {
  const [cfg, setCfg] = useState<Record<string, any>>({});
  const [runs, setRuns] = useState<any[]>([]);
  const [sel, setSel] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [sellers, setSellers] = useState<any[]>([]);
  const curMap = useMemo(() => sidCurrencyMap(sellers), [sellers]);
  const curOf = (sid: any): Cur | undefined => curMap[String(sid)];

  useEffect(() => { void load(); }, []);
  async function load() {
    try {
      const [c, r, sl] = await Promise.all([
        api.get("/lingxing/auto/config"), api.get("/lingxing/auto/runs"),
        api.post("/lingxing/read/sellers", { params: {} }).catch(() => ({ data: { rows: [] } })),
      ]);
      setCfg(c.data.config || {}); setRuns(r.data.runs || []); setSellers(sl.data.rows || []);
    } catch (e: any) { setMsg(humanErr(e)); }
  }
  async function saveCfg() {
    try { const r = await api.patch("/lingxing/auto/config", { config: cfg }); setCfg(r.data.config); setMsg("已保存"); }
    catch (e: any) { setMsg(humanErr(e)); }
  }
  async function runNow() {
    setBusy(true); setMsg("");
    try {
      await api.post("/lingxing/auto/run", {});
      setMsg("已触发，分析中…");
      // poll a few times for the new run to finish
      for (let i = 0; i < 12; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        const r = await api.get("/lingxing/auto/runs");
        setRuns(r.data.runs || []);
        const top = (r.data.runs || [])[0];
        if (top && top.status !== "collecting" && top.status !== "analyzing") { setMsg("完成"); break; }
      }
    } catch (e: any) { setMsg(humanErr(e)); } finally { setBusy(false); }
  }
  async function openRun(id: string) {
    try { const r = await api.get(`/lingxing/auto/runs/${id}`); setSel(r.data); } catch (e: any) { setMsg(humanErr(e)); }
  }

  const set = (k: string, v: any) => setCfg((c) => ({ ...c, [k]: v }));

  return (
    <div>
      {/* config */}
      <div className="card" style={{ padding: 12, marginBottom: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 8 }}>定时建议（仅分析+建议，不写入领星）</div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={lbl}><span>启用定时</span>
            <select value={String(!!cfg.lingxing_auto_enabled)} onChange={(e) => set("lingxing_auto_enabled", e.target.value === "true")} style={{ ...inputStyle, width: 80 }}>
              <option value="false">关</option><option value="true">开</option>
            </select></label>
          <label style={lbl}><span>星期</span>
            <select value={String(cfg.lingxing_auto_weekday ?? 0)} onChange={(e) => set("lingxing_auto_weekday", Number(e.target.value))} style={{ ...inputStyle, width: 80 }}>
              {WEEKDAYS.map((w, i) => <option key={i} value={i}>{w}</option>)}
            </select></label>
          <label style={lbl}><span>小时</span>
            <input value={cfg.lingxing_auto_hour ?? 9} onChange={(e) => set("lingxing_auto_hour", Number(e.target.value))} style={{ ...inputStyle, width: 70 }} /></label>
          <label style={lbl}><span>分析天数</span>
            <input value={cfg.lingxing_auto_report_days ?? 7} onChange={(e) => set("lingxing_auto_report_days", Number(e.target.value))} style={{ ...inputStyle, width: 70 }} /></label>
          <label style={lbl}><span>幅度上限%</span>
            <input value={cfg.lingxing_max_change_pct ?? 20} onChange={(e) => set("lingxing_max_change_pct", Number(e.target.value))} style={{ ...inputStyle, width: 80 }} /></label>
          <label style={lbl}><span>店铺SID(空=全部)</span>
            <input value={cfg.lingxing_auto_stores ?? ""} onChange={(e) => set("lingxing_auto_stores", e.target.value)} style={{ ...inputStyle, width: 160 }} /></label>
          <Btn onClick={saveCfg}>保存配置</Btn>
          <Btn primary onClick={runNow} disabled={busy}>{busy ? "运行中…" : "立即运行一次"}</Btn>
          {msg && <span style={{ fontSize: 11, color: "var(--t3)" }}>{msg}</span>}
        </div>
      </div>

      <div style={{ display: "flex", gap: 12 }}>
        {/* runs list */}
        <div style={{ width: 220, flexShrink: 0 }} className="card">
          <div style={{ padding: "8px 10px", fontSize: 10, color: "var(--t3)", borderBottom: "1px solid var(--b)" }}>运行记录</div>
          {runs.length === 0 && <div style={{ padding: 16, fontSize: 11, color: "var(--t3)" }}>暂无</div>}
          {runs.map((r) => (
            <div key={r.id} onClick={() => openRun(r.id)} style={{
              padding: "7px 10px", cursor: "pointer", borderBottom: "1px solid var(--b)",
              background: sel?.id === r.id ? "var(--bg2)" : "transparent",
            }}>
              <div style={{ fontSize: 11, display: "flex", justifyContent: "space-between" }}>
                <span>{fmtTs(r.started_at)}</span><StatusTag s={r.status} />
              </div>
              <div style={{ fontSize: 10, color: "var(--t3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.trigger === "scheduled" ? "定时" : "手动"} · {r.summary || r.error || "—"}
              </div>
            </div>
          ))}
        </div>

        {/* run detail */}
        <div style={{ flex: 1, minWidth: 0 }} className="card">
          {!sel ? (
            <div style={{ padding: 30, textAlign: "center", color: "var(--t3)", fontSize: 11 }}>选择左侧运行记录查看建议</div>
          ) : (
            <div style={{ padding: 12 }}>
              <div style={{ fontSize: 12, marginBottom: 8 }}>{sel.summary || "（无总结）"}</div>
              {sel.error && <div style={{ color: "var(--red)", fontSize: 11, marginBottom: 8 }}>错误：{sel.error}</div>}
              {(!sel.proposals || sel.proposals.length === 0) ? (
                <div style={{ color: "var(--t3)", fontSize: 11 }}>无建议（数据不足或无明显信号）。</div>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                    <thead><tr>{["活动", "动作", "当前", "建议", "幅度", "依据", "预期", "置信", "风险"].map((h) => (
                      <th key={h} style={th}>{h}</th>))}</tr></thead>
                    <tbody>
                      {sel.proposals.map((p: any, i: number) => (
                        <tr key={i} style={{ borderBottom: "1px solid var(--b)" }}>
                          <td style={td}>{p.campaign_name || p.campaign_id}</td>
                          <td style={td}><b>{p.action}</b></td>
                          <td style={td}>{fmtState(p.current, curOf(p.sid))}</td>
                          <td style={td}>{fmtState(p.proposed, curOf(p.sid))}</td>
                          <td style={td}>{p.change_pct != null ? `${p.change_pct}%` : "—"}{p.guardrail_flag && <span title={p.guardrail_flag} style={{ color: "var(--amber)" }}> ⚠</span>}</td>
                          <td style={{ ...td, maxWidth: 240, whiteSpace: "normal" }}>{p.rationale}</td>
                          <td style={{ ...td, maxWidth: 200, whiteSpace: "normal" }}>{p.expected_impact}</td>
                          <td style={td}>{p.confidence != null ? Math.round(p.confidence * 100) + "%" : "—"}</td>
                          <td style={td}><RiskTag r={p.risk} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div style={{ marginTop: 8, fontSize: 10, color: "var(--t3)" }}>
                    ⓘ 以上为建议态。开启「操作开关」后，这些建议会进入三重复核 + 人工确认才会执行（P3）。
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const lbl: React.CSSProperties = { display: "grid", gap: 3, fontSize: 10, color: "var(--t3)" };
const th: React.CSSProperties = { textAlign: "left", padding: "6px 8px", color: "var(--t3)", borderBottom: "1px solid var(--b)", whiteSpace: "nowrap" };
const td: React.CSSProperties = { padding: "6px 8px", color: "var(--t2)", verticalAlign: "top" };

function StatusTag({ s }: { s: string }) {
  const c = s === "done" ? "var(--acc)" : s === "failed" ? "var(--red)" : "var(--amber)";
  return <span style={{ color: c, fontSize: 10 }}>{s}</span>;
}
function RiskTag({ r }: { r: string }) {
  const c = r === "high" ? "var(--red)" : r === "medium" ? "var(--amber)" : "var(--acc)";
  return <span style={{ color: c }}>{r || "—"}</span>;
}
function fmtState(o: any, cur?: Cur) {
  if (!o || typeof o !== "object") return "—";
  const b = o.daily_budget, s = o.state;
  return [s, b != null ? fmtBudget(b, cur) : null].filter(Boolean).join(" / ") || "—";
}
function fmtTs(ts?: string) { if (!ts) return "—"; try { return new Date(ts).toLocaleString("zh-CN", { hour12: false }); } catch { return ts; } }
function humanErr(e: any): string { return e?.response?.data?.detail || e?.message || "请求失败"; }
