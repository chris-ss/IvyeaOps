import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { sidCurrencyMap, fmtBudget, type Cur } from "./lingxingCurrency";
import { useConfirm } from "../../components/ConfirmDialog";
import SheetSelect from "../../components/SheetSelect";

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
  const [opTypes, setOpTypes] = useState<any[]>([]);
  const [mForm, setMForm] = useState<any>({ op_type: "keyword_bid" });
  const [showManual, setShowManual] = useState(false);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const curMap = useMemo(() => sidCurrencyMap(sellers), [sellers]);
  const curOf = (sid: any): Cur | undefined => curMap[String(sid)];
  const confirm = useConfirm();

  useEffect(() => { void load(); const t = setInterval(refreshStatus, 5000); return () => clearInterval(t); }, []);
  async function load() {
    try {
      const [s, t, r, sl, ot] = await Promise.all([
        api.get("/lingxing/status"), api.get("/lingxing/operate/tickets"), api.get("/lingxing/auto/runs"),
        api.post("/lingxing/read/sellers", { params: {} }).catch(() => ({ data: { rows: [] } })),
        api.get("/lingxing/operate/op-types").catch(() => ({ data: { op_types: [] } })),
      ]);
      setStatus(s.data); setTickets(t.data.tickets || []); setRuns(r.data.runs || []);
      setSellers(sl.data.rows || []); setOpTypes(ot.data.op_types || []);
      if (!mForm.sid && sl.data.rows?.[0]) setMForm((f: any) => ({ ...f, sid: sl.data.rows[0].sid }));
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
  async function submitManual() {
    setBusy(true); setMsg("");
    try {
      const r = await api.post("/lingxing/operate/manual", mForm);
      setMsg(`已创建工单 ${r.data.id}（${r.data.status}）`);
      setShowManual(false); await refreshTickets(); setSel(r.data);
    } catch (e: any) { setMsg(humanErr(e)); } finally { setBusy(false); }
  }
  const mSet = (k: string, v: any) => setMForm((f: any) => ({ ...f, [k]: v }));
  async function report(tid: string, download: boolean) {
    try {
      const r = await api.get(`/lingxing/operate/tickets/${tid}/report?download=${download ? 1 : 0}`, { responseType: "blob" });
      const url = URL.createObjectURL(r.data as Blob);
      if (download) {
        const a = document.createElement("a"); a.href = url; a.download = `lingxing-op-${tid}.html`; a.click();
      } else { window.open(url, "_blank"); }
      setTimeout(() => URL.revokeObjectURL(url), 15000);
    } catch (e: any) { setMsg(humanErr(e)); }
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
              : <Btn danger onClick={async () => { if (await confirm({ title: "开启操作开关", message: "开启后进入可写态（写操作仍需三重复核 + 护栏 + 人工确认）。确定开启？", confirmText: "开启", danger: true, icon: "⚠" })) toggleOperate(true); }} disabled={busy}>开启操作领星</Btn>}
          </span>
        </div>
        <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 8 }}>
          每一笔写操作都必须：① 三重独立复核全过 → ② 确定性护栏（白名单/幅度上限）→ ③ 你人工点确认 → 才执行；执行前抓回滚快照，失败自动熔断。{!status?.master_enabled && " （注意：总开关未开启，写操作仍会被拦截）"}
        </div>
      </div>

      {/* generate tickets from a run */}
      <div className="card" style={{ padding: 12, marginBottom: 10, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: "var(--t3)" }}>从分析运行生成工单</span>
        <SheetSelect value={runId} onChange={setRunId} title="选择分析运行" placeholder="（无运行记录）" style={{ ...inputStyle, minWidth: 220 }}
          options={runs.map((r) => ({ value: String(r.id), label: `${fmtTs(r.started_at)} · ${r.summary?.slice(0, 20) || r.status}` }))} />
        <Btn onClick={genFromRun} disabled={busy || !runId}>生成工单（进入复核）</Btn>
        <span style={{ marginLeft: "auto" }}><Btn onClick={() => setShowManual((v) => !v)}>{showManual ? "收起" : "＋ 新建工单"}</Btn></span>
        {msg && <span style={{ fontSize: 11, color: "var(--t3)" }}>{msg}</span>}
      </div>

      {/* manual ticket — dynamic fields per op type */}
      {showManual && (() => {
        const op = opTypes.find((o) => o.key === mForm.op_type);
        return (
          <div className="card" style={{ padding: 12, marginBottom: 10 }}>
            <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 8 }}>新建写操作工单（走 三复核 + 护栏 + 人工确认）</div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
              <L t="操作类型"><SheetSelect value={mForm.op_type} onChange={(v) => setMForm({ op_type: v, sid: mForm.sid })} title="操作类型" style={{ ...inputStyle, minWidth: 170 }}
                options={opTypes.map((o) => ({ value: o.key, label: o.label }))} /></L>
              <L t="店铺"><SheetSelect value={String(mForm.sid ?? "")} onChange={(v) => mSet("sid", Number(v))} title="选择店铺" style={{ ...inputStyle, minWidth: 140 }}
                options={sellers.map((s) => ({ value: String(s.sid), label: String(s.name || s.sid) }))} /></L>
              {(op?.fields || []).map((f: any) => (
                <L key={f.name} t={f.label + (f.required ? " *" : "")}>
                  {f.type === "select"
                    ? <SheetSelect value={String(mForm[f.name] ?? "")} onChange={(v) => mSet(f.name, v)} title={f.label} placeholder="不改" style={{ ...inputStyle, minWidth: 110 }}
                        options={f.options.map((o: string) => ({ value: o, label: o || "不改" }))} />
                    : <input value={mForm[f.name] ?? ""} onChange={(e) => mSet(f.name, e.target.value)}
                        style={{ ...inputStyle, width: f.type === "number" ? 100 : 150 }} placeholder={f.type === "number" ? "数字" : ""} />}
                </L>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "flex-end" }}>
              <L t="依据/理由"><input value={mForm.rationale ?? ""} onChange={(e) => mSet("rationale", e.target.value)} style={{ ...inputStyle, width: 420 }} placeholder="为什么这么做（复核会读）" /></L>
              <Btn primary onClick={submitManual} disabled={busy || !mForm.sid}>提交进复核</Btn>
            </div>
            <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 6 }}>
              {op?.category === "add"
                ? `加词/否词为新增操作${op?.reversible ? "（回滚=归档该否定词）" : "（不可一键回滚，撤销请到领星暂停/归档）"}；活动/广告组ID 可在「数据浏览」对应数据集查到。`
                : "改竞价/预算：当前值自动读取真实值算幅度护栏；目标ID 在「数据浏览」SP关键词/定向/广告组里查；回滚以执行前真实值为快照。"}
            </div>
          </div>
        );
      })()}

      <div className="lx-split">
        {/* tickets list */}
        <div style={{ width: 230 }} className="card lx-side">
          <div style={{ padding: "8px 10px", fontSize: 10, color: "var(--t3)", borderBottom: "1px solid var(--b)" }}>工单</div>
          {tickets.length === 0 && <div style={{ padding: 16, fontSize: 11, color: "var(--t3)" }}>暂无</div>}
          {tickets.map((t) => (
            <div key={t.id} onClick={() => openTicket(t.id)} style={{
              padding: "7px 10px", cursor: "pointer", borderBottom: "1px solid var(--b)",
              background: sel?.id === t.id ? "var(--bg2)" : "transparent",
            }}>
              <div style={{ fontSize: 11, display: "flex", justifyContent: "space-between", gap: 6 }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.intent?.target_name || t.intent?.campaign_name || t.intent?.target_id || t.intent?.campaign_id}</span>
                <TicketStatus s={t.status} />
              </div>
              <div style={{ fontSize: 10, color: "var(--t3)" }}>{t.intent?.keyword_text ? `「${t.intent.keyword_text}」${t.intent.match_type || ""}` : fmtChange(t.intent?.change, curOf(t.intent?.sid))}</div>
            </div>
          ))}
        </div>

        {/* ticket detail */}
        <div className="card lx-main">
          {!sel ? <div style={{ padding: 30, textAlign: "center", color: "var(--t3)", fontSize: 11 }}>选择左侧工单</div> : (
            <div style={{ padding: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <b style={{ fontSize: 12 }}>{sel.intent?.target_name || sel.intent?.campaign_name || sel.intent?.target_id || sel.intent?.campaign_id}</b>
                {sel.intent?.op_label && <span style={{ fontSize: 10, color: "var(--t3)", border: "1px solid var(--b)", borderRadius: 3, padding: "1px 5px" }}>{sel.intent.op_label}</span>}
                <TicketStatus s={sel.status} />
                <span style={{ fontSize: 11, color: "var(--t3)" }}>店铺 {sel.intent?.sid}</span>
              </div>
              <div style={{ fontSize: 11, marginBottom: 8 }}>
                {sel.intent?.keyword_text
                  ? <>新增：<b>「{sel.intent.keyword_text}」（{sel.intent.match_type}）</b> 活动 {sel.intent.campaign_id}{sel.intent.ad_group_id ? ` / 组 ${sel.intent.ad_group_id}` : ""}{sel.intent.bid != null ? ` / 竞价 ${fmtBudget(sel.intent.bid, curOf(sel.intent.sid))}` : ""}<br /></>
                  : <>改动：<b>{fmtChange(sel.intent?.change, curOf(sel.intent?.sid))}</b>（当前 {fmtState(sel.intent?.before, curOf(sel.intent?.sid))}）<br /></>}
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
                    {" · "}<b>{r.reviewer}</b>{r.provider && <span style={{ color: "var(--t3)" }}> [{({ "ivyea-agent": "IvyeaAgent", assistant: "全局兜底", deepseek: "DeepSeek", apimart: "Claude", fallback: "兜底", none: "不可用" } as any)[r.provider] || r.provider}]</span>}{" · 风险 "}{Math.round((r.risk_score ?? 1) * 100)}%
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
                <Btn onClick={() => report(sel.id, false)}>预览报告</Btn>
                <Btn onClick={() => report(sel.id, true)}>下载报告</Btn>
                {sel.status === "awaiting_human" && <>
                  <Btn onClick={() => act(sel.id, "confirm", { dry_run: true })} disabled={busy}>预览请求</Btn>
                  <Btn danger onClick={async () => { if (await confirm({ title: "确认执行写操作", message: `将真实写入领星：${sel.intent?.target_name || sel.intent?.target_id}。已通过三重复核 + 护栏，确定执行？`, confirmText: "确认执行", danger: true, icon: "⚠" })) act(sel.id, "confirm", { dry_run: false }); }} disabled={busy || !active}>确认执行</Btn>
                  <Btn onClick={() => act(sel.id, "reject")} disabled={busy}>驳回</Btn>
                  {!active && <span style={{ fontSize: 10, color: "var(--amber)", alignSelf: "center" }}>需先开启操作开关</span>}
                </>}
                {sel.status === "executed" && <Btn onClick={async () => { if (await confirm({ title: "回滚操作", message: "回滚到执行前的快照状态？", confirmText: "回滚", danger: true, icon: "⚠" })) act(sel.id, "rollback"); }} disabled={busy || !active}>回滚</Btn>}
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
function numField(o: any): [string, any] {
  if (o?.daily_budget != null) return ["预算", o.daily_budget];
  if (o?.bid != null) return ["竞价", o.bid];
  if (o?.defaultBid != null) return ["默认竞价", o.defaultBid];
  return ["", null];
}
function fmtChange(c: any, cur?: Cur) {
  if (!c) return "—";
  const a = []; const [lbl, v] = numField(c);
  if (v != null) a.push(`${lbl}→${fmtBudget(v, cur)}`);
  if (c.state) a.push(`状态→${c.state}`);
  return a.join(" / ") || "—";
}
function fmtState(o: any, cur?: Cur) { if (!o) return "—"; const a = []; if (o.state) a.push(o.state); const [, v] = numField(o); if (v != null) a.push(fmtBudget(v, cur)); return a.join(" / ") || "—"; }
function L({ t, children }: { t: string; children: any }) {
  return <div style={{ display: "grid", gap: 3, fontSize: 10, color: "var(--t3)" }}><span>{t}</span>{children}</div>;
}
function fmtDur(s: number) { const m = Math.floor(s / 60); return m >= 60 ? `${Math.floor(m / 60)}h${m % 60}m` : `${m}m`; }
function fmtTs(ts?: string) { if (!ts) return "—"; try { return new Date(ts).toLocaleString("zh-CN", { hour12: false }); } catch { return ts; } }
function humanErr(e: any): string { return e?.response?.data?.detail || e?.message || "请求失败"; }
