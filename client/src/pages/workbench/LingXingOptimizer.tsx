import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { sidCurrencyMap, fmtBudget, type Cur } from "./lingxingCurrency";

const inputStyle: React.CSSProperties = {
  background: "var(--bg1)", border: "1px solid var(--b)", borderRadius: 3,
  padding: "5px 7px", fontSize: 11, color: "var(--t)", outline: "none", fontFamily: "inherit", boxSizing: "border-box",
};
function Btn({ onClick, children, primary, disabled }: any) {
  return <button onClick={onClick} disabled={disabled} style={{ background: primary ? "var(--acc)" : "var(--bg2)", color: primary ? "#000" : "var(--t)", border: primary ? "none" : "1px solid var(--b)", borderRadius: 4, padding: "4px 10px", fontSize: 11, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.55 : 1 }}>{children}</button>;
}
const LEVER_COLOR: Record<string, string> = { "否词": "var(--red)", "降bid": "var(--amber)", "加bid": "var(--acc)", "加预算": "var(--blue)", "收割": "var(--purple)" };
const pct = (v: any) => (v == null ? "—" : (v * 100).toFixed(0) + "%");

export default function LingXingOptimizer({ storeSid }: { storeSid?: string }) {
  const [sellers, setSellers] = useState<any[]>([]);
  const [sid, setSid] = useState<string>(storeSid || "");
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState<Record<number, string>>({});
  const cur: Cur | undefined = sidCurrencyMap(sellers)[sid];

  useEffect(() => { void load(); }, []);
  async function load() {
    try {
      const r = await api.post("/lingxing/read/sellers", { params: {} });
      setSellers(r.data.rows || []);
      if (!sid && r.data.rows?.[0]) setSid(String(r.data.rows[0].sid));
    } catch (e: any) { setErr(humanErr(e)); }
  }
  async function run() {
    if (!sid) return;
    setLoading(true); setErr(""); setData(null); setDone({});
    try { setData((await api.get(`/lingxing/optimizer/run?sid=${sid}&days=${days}`)).data); }
    catch (e: any) { setErr(humanErr(e)); } finally { setLoading(false); }
  }
  async function makeTicket(c: any, i: number) {
    try {
      const r = await api.post("/lingxing/operate/manual", c.payload);
      setDone((d) => ({ ...d, [i]: r.data.id }));
    } catch (e: any) { setErr(humanErr(e)); }
  }

  return (
    <div>
      <div className="card" style={{ padding: 12, marginBottom: 10, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: "var(--t3)" }}>店铺</span>
        <select value={sid} onChange={(e) => setSid(e.target.value)} style={{ ...inputStyle, minWidth: 150 }}>
          {sellers.map((s) => <option key={s.sid} value={String(s.sid)}>{s.name || s.sid}</option>)}
        </select>
        <span style={{ fontSize: 11, color: "var(--t3)" }}>窗口</span>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ ...inputStyle, width: 90 }}>
          {[14, 30, 60].map((d) => <option key={d} value={d}>近 {d} 天</option>)}
        </select>
        <Btn primary onClick={run} disabled={loading}>{loading ? "分析中…(首次较慢)" : "运行优化引擎"}</Btn>
        {err && <span style={{ fontSize: 11, color: "var(--red)" }}>{err}</span>}
      </div>

      {data && (
        <div className="card" style={{ padding: "8px 12px", marginBottom: 10, fontSize: 11 }}>
          <b>{data.note}</b> · 候选 <b>{data.count}</b> 条 · 窗口 {data.window_days} 天（已剔除近 2 天）
          <span style={{ color: "var(--t3)" }}> —— 规则算出、可审计；点「生成工单」进 三复核 + 护栏 + 人工确认。</span>
        </div>
      )}

      {data && (data.candidates || []).length === 0 && !loading && (
        <div className="card" style={{ padding: 30, textAlign: "center", color: "var(--t3)", fontSize: 11 }}>窗口内无达阈值的优化候选（数据不足或表现平稳）。</div>
      )}

      {data && (data.candidates || []).map((c: any, i: number) => (
        <div key={i} className="card" style={{ padding: 10, marginBottom: 8, borderLeft: `3px solid ${LEVER_COLOR[c.lever] || "var(--b)"}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: LEVER_COLOR[c.lever] }}>{c.lever}</span>
            <b style={{ fontSize: 12 }}>{c.target_name}</b>
            {c.current && c.proposed && (
              <span style={{ fontSize: 11, color: "var(--t2)" }}>
                {fmtVal(c.current, cur)} → <b>{fmtVal(c.proposed, cur)}</b>
                {c.change_pct != null && <span style={{ color: "var(--t3)" }}> ({c.change_pct}%)</span>}
              </span>
            )}
            <span style={{ marginLeft: "auto" }}>
              {c.advisory
                ? <span style={{ fontSize: 10, color: "var(--purple)" }}>建议（需指定目标精准活动）</span>
                : done[i]
                  ? <span style={{ fontSize: 10, color: "var(--acc)" }}>✓ 工单 {done[i]}</span>
                  : <Btn onClick={() => makeTicket(c, i)}>生成工单</Btn>}
            </span>
          </div>
          <div style={{ fontSize: 11, color: "var(--t2)", marginTop: 4 }}>{c.rule}</div>
          <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 2 }}>
            显著性：{c.significance} · 花费 {fmtBudget(c.metrics?.spend, cur)} · 销售 {fmtBudget(c.metrics?.sales, cur)} · ACOS {pct(c.metrics?.acos)} · 订单 {c.metrics?.orders} · 点击 {c.metrics?.clicks}
          </div>
        </div>
      ))}
    </div>
  );
}

function fmtVal(o: any, cur?: Cur) {
  if (o?.bid != null) return fmtBudget(o.bid, cur);
  if (o?.daily_budget != null) return fmtBudget(o.daily_budget, cur);
  if (o?.defaultBid != null) return fmtBudget(o.defaultBid, cur);
  return "—";
}
function humanErr(e: any): string { return e?.response?.data?.detail || e?.message || "请求失败"; }
