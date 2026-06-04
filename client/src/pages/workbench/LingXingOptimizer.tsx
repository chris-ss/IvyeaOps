import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { sidCurrencyMap, fmtBudget, type Cur } from "./lingxingCurrency";
import SheetSelect from "../../components/SheetSelect";

const inputStyle: React.CSSProperties = {
  background: "var(--bg1)", border: "1px solid var(--b)", borderRadius: 3,
  padding: "5px 7px", fontSize: 11, color: "var(--t)", outline: "none", fontFamily: "inherit", boxSizing: "border-box",
};
function Btn({ onClick, children, primary, disabled }: any) {
  return <button onClick={onClick} disabled={disabled} style={{ background: primary ? "var(--acc)" : "var(--bg2)", color: primary ? "#000" : "var(--t)", border: primary ? "none" : "1px solid var(--b)", borderRadius: 4, padding: "4px 10px", fontSize: 11, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.55 : 1 }}>{children}</button>;
}
const LEVER_COLOR: Record<string, string> = { "否词": "var(--red)", "降bid": "var(--amber)", "加bid": "var(--acc)", "加预算": "var(--blue)", "收割": "var(--purple)" };
const pct = (v: any) => (v == null ? "—" : (v * 100).toFixed(0) + "%");

// module-level cache so a run (and its in-flight request) survives tab switches
type OptEntry = { data?: any; loading?: boolean; promise?: Promise<any>; done?: Record<number, string> };
const optCache: Record<string, OptEntry> = {};

export default function LingXingOptimizer({ storeSid }: { storeSid?: string }) {
  const [sellers, setSellers] = useState<any[]>([]);
  const sid = storeSid || "";   // store is driven by the page-level selector
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState<Record<number, string>>({});
  const [campaigns, setCampaigns] = useState<any[]>([]);
  const [adgroups, setAdgroups] = useState<any[]>([]);
  const [hForm, setHForm] = useState<Record<number, any>>({});
  const setH = (i: number, k: string, v: any) => setHForm((f) => ({ ...f, [i]: { ...f[i], [k]: v } }));
  const markDone = (i: number, id: string) => setDone((d) => { const n = { ...d, [i]: id }; if (optCache[sid]) optCache[sid].done = n; return n; });
  const cur: Cur | undefined = sidCurrencyMap(sellers)[sid];

  useEffect(() => { void load(); }, []);
  async function load() {
    try {
      const r = await api.post("/lingxing/read/sellers", { params: {} });
      setSellers(r.data.rows || []);
    } catch (e: any) { setErr(humanErr(e)); }
  }
  // restore from cache on mount / store change (keeps the running indicator + result)
  useEffect(() => {
    const c = optCache[sid];
    setData(c?.data ?? null); setDone(c?.done ?? {}); setErr("");
    if (c?.loading && c.promise) {
      setLoading(true);
      c.promise.then((d) => setData(d)).catch(() => {}).finally(() => setLoading(false));
    } else { setLoading(false); }
    if (c?.data?.candidates?.some((x: any) => x.harvest)) void loadDest();
  }, [storeSid]);
  async function run() {
    if (!sid) return;
    setLoading(true); setErr(""); setData(null); setDone({});
    const p = api.get(`/lingxing/optimizer/run?sid=${sid}&days=${days}`).then((r) => r.data);
    optCache[sid] = { loading: true, promise: p, done: {} };
    try {
      const d = await p;
      optCache[sid] = { data: d, loading: false, done: {} };
      setData(d);
      if ((d.candidates || []).some((c: any) => c.harvest)) void loadDest();
    } catch (e: any) { setErr(humanErr(e)); optCache[sid] = { loading: false }; }
    finally { setLoading(false); }
  }
  async function loadDest() {
    try {
      const [cp, ag] = await Promise.all([
        api.post("/lingxing/read/sp_campaigns", { params: { sid: Number(sid), length: 300 } }),
        api.post("/lingxing/read/sp_adgroups", { params: { sid: Number(sid), length: 300 } }),
      ]);
      setCampaigns((cp.data.rows || []).filter((c: any) => c.targeting_type === "manual"));
      setAdgroups(ag.data.rows || []);
    } catch { /* */ }
  }
  async function makeTicket(c: any, i: number) {
    try {
      const r = await api.post("/lingxing/operate/manual", c.payload);
      markDone(i, r.data.id);
    } catch (e: any) { setErr(humanErr(e)); }
  }
  async function makeHarvest(c: any, i: number) {
    const h = hForm[i] || {};
    if (!h.campaign_id || !h.ad_group_id) return;
    try {
      const r = await api.post("/lingxing/operate/manual", {
        op_type: "add_keyword", sid: Number(sid), campaign_id: h.campaign_id, ad_group_id: h.ad_group_id,
        keyword_text: c.harvest.query, match_type: "EXACT", bid: Number(h.bid ?? c.harvest.suggested_bid),
        rationale: `收割：搜索词「${c.harvest.query}」已 ${c.metrics?.orders} 单，加入精准活动，建议bid ${c.harvest.suggested_bid}`,
        opt: { lever: "收割", rule: c.rule, significance: c.significance, metrics: c.metrics, target_acos: c.opt_target, breakeven_acos: c.opt_breakeven },
      });
      markDone(i, r.data.id);
    } catch (e: any) { setErr(humanErr(e)); }
  }

  return (
    <div>
      <div className="card" style={{ padding: 12, marginBottom: 10, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: "var(--t3)" }}>店铺：{sellers.find((s) => String(s.sid) === sid)?.name || sid || "（上方选择）"}</span>
        <span style={{ fontSize: 11, color: "var(--t3)" }}>窗口</span>
        <SheetSelect value={String(days)} onChange={(v) => setDays(Number(v))} title="时间窗口" style={{ ...inputStyle, width: 100 }}
          options={[14, 30, 60].map((d) => ({ value: String(d), label: `近 ${d} 天` }))} />
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
              {c.harvest
                ? (done[i]
                  ? <span style={{ fontSize: 10, color: "var(--acc)" }}>✓ 工单 {done[i]}</span>
                  : <span style={{ display: "inline-flex", gap: 5, alignItems: "center", flexWrap: "wrap" }}>
                      <SheetSelect value={String(hForm[i]?.campaign_id || "")} onChange={(v) => setH(i, "campaign_id", v)} title="目标活动(manual)" placeholder="目标活动" style={{ ...inputStyle, maxWidth: 140 }}
                        options={campaigns.map((cp) => ({ value: String(cp.campaign_id), label: String(cp.name || cp.campaign_id) }))} />
                      <SheetSelect value={String(hForm[i]?.ad_group_id || "")} onChange={(v) => setH(i, "ad_group_id", v)} title="广告组" placeholder="广告组" style={{ ...inputStyle, maxWidth: 120 }}
                        options={adgroups.filter((a) => String(a.campaign_id) === String(hForm[i]?.campaign_id)).map((a) => ({ value: String(a.ad_group_id), label: String(a.name || a.ad_group_id) }))} />
                      <input value={hForm[i]?.bid ?? c.harvest.suggested_bid} onChange={(e) => setH(i, "bid", e.target.value)} style={{ ...inputStyle, width: 64 }} title="精准词bid" />
                      <Btn onClick={() => makeHarvest(c, i)} disabled={!hForm[i]?.campaign_id || !hForm[i]?.ad_group_id}>生成工单</Btn>
                    </span>)
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
