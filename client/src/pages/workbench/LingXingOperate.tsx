import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { sidCurrencyMap, fmtBudget, type Cur } from "./lingxingCurrency";

const inputStyle: React.CSSProperties = {
  background: "var(--bg1)", border: "1px solid var(--b)", borderRadius: 3,
  padding: "5px 7px", fontSize: 11, color: "var(--t)", outline: "none", fontFamily: "inherit", boxSizing: "border-box",
};
function Btn({ onClick, children, primary, danger, disabled }: any) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      background: danger ? "var(--red)" : primary ? "var(--acc)" : "var(--bg2)",
      color: danger || primary ? "#000" : "var(--t)", border: danger || primary ? "none" : "1px solid var(--b)",
      borderRadius: 4, padding: "5px 12px", fontSize: 11, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.55 : 1,
    }}>{children}</button>
  );
}

export default function LingXingOperate() {
  const [status, setStatus] = useState<any>(null);
  const [tickets, setTickets] = useState<any[]>([]);
  const [sel, setSel] = useState<any | null>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [runId, setRunId] = useState("");
  const [sellers, setSellers] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const curMap = useMemo(() => sidCurrencyMap(sellers), [sellers]);
  const curOf = (sid: any): Cur | undefined => curMap[String(sid)];

  useEffect(() => { void load(); const t = setInterval(refreshStatus, 5000); return () => clearInterval(t); }, []);
  async function load() {
    try {
      const [s, t, r, sl] = await Promise.all([
        api.get("/lingxing/status"), api.get("/lingxing/operate/tickets"), api.get("/lingxing/auto/runs"),
        api.post("/lingxing/read/sellers", { params: {} }).catch(() => ({ data: { rows: [] } })),
      ]);
      setStatus(s.data); setTickets(t.data.tickets || []); setRuns(r.data.runs || []);
      setSellers(sl.data.rows || []);
      if (!runId && r.data.runs?.[0]) setRunId(r.data.runs[0].id);
    } catch (e: any) { setMsg(humanErr(e)); }
  }
  async function refreshStatus() { try { setStatus((await api.get("/lingxing/status")).data); } catch { /* */ } }
  async function refreshTickets() { try { setTickets((await api.get("/lingxing/operate/tickets")).data.tickets || []); } catch { /* */ } }

  async function toggleOperate(on: boolean) {
    setBusy(true); setMsg("");
    try { const r = await api.post(`/lingxing/operate/${on ? "enable" : "disable"}`); setStatus(r.data.status); }
    catch (e: any) { setMsg(humanErr(e)); } finally { setBusy(false); }
  }
  async function genFromRun() {
    if (!runId) return;
    setBusy(true); setMsg("");
    try { const r = await api.post(`/lingxing/operate/from-run/${runId}`); setMsg(`已生成 ${r.data.created} 个工单`); await refreshTickets(); }
    catch (e: any) { setMsg(humanErr(e)); } finally { setBusy(false); }
  }
  async function openTicket(id: string) { try { setSel((await api.get(`/lingxing/operate/tickets/${id}`)).data); } catch (e: any) { setMsg(humanErr(e)); } }
  async function act(id: string, action: string, body: any = {}) {
    setBusy(true); setMsg("");
    try {
      const r = await api.post(`/lingxing/operate/tickets/${id}/${action}`, body);
      setSel(r.data); await refreshTickets(); await refreshStatus();
    } catch (e: any) { setMsg(humanErr(e)); } finally { setBusy(false); }
  }

  const active = !!status?.operate_active;
  const remain = status?.operate_remaining_seconds || 0;

  return (
    <div>
      {/* circuit breaker tripped */}
      {status?.circuit_reason && (
        <div className="card" style={{ padding: "10px 12px", marginBottom: 10, border: "1px solid var(--red)", background: "color-mix(in srgb, var(--red) 8%, transparent)" }}>
          <span style={{ fontSize: 11, color: "var(--red)", fontWeight: 600 }}>⚠ 熔断已触发：</span>
          <span style={{ fontSize: 11, color: "var(--t2)" }}> {status.circuit_reason}</span>
          <span style={{ fontSize: 10, color: "var(--t3)" }}>（重新开启操作开关即确认并清除）</span>
        </div>
      )}

      {/* operate switch (danger) */}
      <div className="card" style={{ padding: 12, marginBottom: 10, border: active ? "1px solid var(--red)" : "1px solid var(--b)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: active ? "var(--red)" : "var(--t)" }}>
            操作开关：{active ? "已开启（可写）" : "关闭（只读）"}
          </div>
          {active && <span style={{ fontSize: 11, color: "var(--amber)" }}>剩余 {fmtDur(remain)} 后自动关闭</span>}
          <span style={{ marginLeft: "auto" }}>
            {active
              ? <Btn onClick={() => toggleOperate(false)} disabled={busy}>关闭操作</Btn>
              : <Btn danger onClick={() => toggleOperate(true)} disabled={busy}>开启操作领星</Btn>}
          </span>
        </div>
        <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 8 }}>
          每一笔写操作都必须：① 三重独立复核全过 → ② 确定性护栏（白名单/幅度上限）→ ③ 你人工点确认 → 才执行；执行前抓回滚快照，失败自动熔断。{!status?.master_enabled && " （注意：总开关未开启，写操作仍会被拦截）"}
        </div>
      </div>

      {/* generate tickets from a run */}
      <div className="card" style={{ padding: 12, marginBottom: 10, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: "var(--t3)" }}>从分析运行生成工单</span>
        <select value={runId} onChange={(e) => setRunId(e.target.value)} style={{ ...inputStyle, minWidth: 220 }}>
          {runs.length === 0 && <option value="">（无运行记录）</option>}
          {runs.map((r) => <option key={r.id} value={r.id}>{fmtTs(r.started_at)} · {r.summary?.slice(0, 20) || r.status}</option>)}
        </select>
        <Btn onClick={genFromRun} disabled={busy || !runId}>生成工单（进入复核）</Btn>
        {msg && <span style={{ fontSize: 11, color: "var(--t3)" }}>{msg}</span>}
      </div>

      <div style={{ display: "flex", gap: 12 }}>
        {/* tickets list */}
        <div style={{ width: 230, flexShrink: 0 }} className="card">
          <div style={{ padding: "8px 10px", fontSize: 10, color: "var(--t3)", borderBottom: "1px solid var(--b)" }}>工单</div>
          {tickets.length === 0 && <div style={{ padding: 16, fontSize: 11, color: "var(--t3)" }}>暂无</div>}
          {tickets.map((t) => (
            <div key={t.id} onClick={() => openTicket(t.id)} style={{
              padding: "7px 10px", cursor: "pointer", borderBottom: "1px solid var(--b)",
              background: sel?.id === t.id ? "var(--bg2)" : "transparent",
            }}>
              <div style={{ fontSize: 11, display: "flex", justifyContent: "space-between", gap: 6 }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.intent?.campaign_name || t.intent?.campaign_id}</span>
                <TicketStatus s={t.status} />
              </div>
              <div style={{ fontSize: 10, color: "var(--t3)" }}>{fmtChange(t.intent?.change, curOf(t.intent?.sid))}</div>
            </div>
          ))}
        </div>

        {/* ticket detail */}
        <div style={{ flex: 1, minWidth: 0 }} className="card">
          {!sel ? <div style={{ padding: 30, textAlign: "center", color: "var(--t3)", fontSize: 11 }}>选择左侧工单</div> : (
            <div style={{ padding: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <b style={{ fontSize: 12 }}>{sel.intent?.campaign_name || sel.intent?.campaign_id}</b>
                <TicketStatus s={sel.status} />
                <span style={{ fontSize: 11, color: "var(--t3)" }}>店铺 {sel.intent?.sid}</span>
              </div>
              <div style={{ fontSize: 11, marginBottom: 8 }}>
                改动：<b>{fmtChange(sel.intent?.change, curOf(sel.intent?.sid))}</b>（当前 {fmtState(sel.intent?.before, curOf(sel.intent?.sid))}）<br />
                依据：<span style={{ color: "var(--t2)" }}>{sel.intent?.rationale || "—"}</span>
              </div>

              {/* guardrails */}
              <Section title="确定性护栏">
                {(sel.guardrail?.checks || []).map((c: any, i: number) => (
                  <div key={i} style={{ fontSize: 11, color: c.ok ? "var(--acc)" : "var(--red)" }}>
                    {c.ok ? "✓" : "✗"} {c.name} <span style={{ color: "var(--t3)" }}>{c.detail}</span>
                  </div>
                ))}
              </Section>

              {/* reviews */}
              <Section title={`三重复核 ${sel.reviews?.approved ? "（全过）" : "（未通过）"}`}>
                {(sel.reviews?.reviews || []).map((r: any, i: number) => (
                  <div key={i} style={{ fontSize: 11, marginBottom: 4 }}>
                    <span style={{ color: r.approve ? "var(--acc)" : "var(--red)" }}>{r.approve ? "批准" : "否决"}</span>
                    {" · "}<b>{r.reviewer}</b>{" · 风险 "}{Math.round((r.risk_score ?? 1) * 100)}%
                    <div style={{ color: "var(--t3)" }}>{r.reasons}</div>
                  </div>
                ))}
              </Section>

              {sel.result?.dry_run && (
                <Section title="预览（将发送的请求）">
                  <pre style={{ fontSize: 10, color: "var(--t2)", whiteSpace: "pre-wrap" }}>{JSON.stringify(sel.result.body, null, 1)}</pre>
                </Section>
              )}
              {sel.error && <div style={{ color: "var(--red)", fontSize: 11, margin: "6px 0" }}>错误：{sel.error}</div>}

              {/* actions */}
              <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                {sel.status === "awaiting_human" && <>
                  <Btn onClick={() => act(sel.id, "confirm", { dry_run: true })} disabled={busy}>预览请求</Btn>
                  <Btn danger onClick={() => { if (confirm("确认执行该写操作到领星？")) act(sel.id, "confirm", { dry_run: false }); }} disabled={busy || !active}>确认执行</Btn>
                  <Btn onClick={() => act(sel.id, "reject")} disabled={busy}>驳回</Btn>
                  {!active && <span style={{ fontSize: 10, color: "var(--amber)", alignSelf: "center" }}>需先开启操作开关</span>}
                </>}
                {sel.status === "executed" && <Btn onClick={() => { if (confirm("回滚到执行前状态？")) act(sel.id, "rollback"); }} disabled={busy || !active}>回滚</Btn>}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: any) {
  return (
    <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--b)" }}>
      <div style={{ fontSize: 10, color: "var(--t3)", marginBottom: 4 }}>{title}</div>{children}
    </div>
  );
}
function TicketStatus({ s }: { s: string }) {
  const map: Record<string, string> = {
    awaiting_human: "var(--amber)", executed: "var(--acc)", rolled_back: "var(--blue)",
    guardrail_blocked: "var(--red)", review_rejected: "var(--red)", rejected: "var(--t3)", failed: "var(--red)",
  };
  const zh: Record<string, string> = {
    reviewing: "复核中", awaiting_human: "待确认", executed: "已执行", rolled_back: "已回滚",
    guardrail_blocked: "护栏拦截", review_rejected: "复核否决", rejected: "已驳回", failed: "失败", executing: "执行中",
  };
  return <span style={{ fontSize: 10, color: map[s] || "var(--t3)" }}>{zh[s] || s}</span>;
}
function fmtChange(c: any, cur?: Cur) {
  if (!c) return "—";
  const a = [];
  if (c.daily_budget != null) a.push(`预算→${fmtBudget(c.daily_budget, cur)}`);
  if (c.state) a.push(`状态→${c.state}`);
  return a.join(" / ") || "—";
}
function fmtState(o: any, cur?: Cur) { if (!o) return "—"; const a = []; if (o.state) a.push(o.state); if (o.daily_budget != null) a.push(fmtBudget(o.daily_budget, cur)); return a.join(" / ") || "—"; }
function fmtDur(s: number) { const m = Math.floor(s / 60); return m >= 60 ? `${Math.floor(m / 60)}h${m % 60}m` : `${m}m`; }
function fmtTs(ts?: string) { if (!ts) return "—"; try { return new Date(ts).toLocaleString("zh-CN", { hour12: false }); } catch { return ts; } }
function humanErr(e: any): string { return e?.response?.data?.detail || e?.message || "请求失败"; }
