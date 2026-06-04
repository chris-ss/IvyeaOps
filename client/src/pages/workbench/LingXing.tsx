import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import LingXingAutomation from "./LingXingAutomation";
import LingXingOperate from "./LingXingOperate";
import LingXingAudit from "./LingXingAudit";

/* ── shared mini-styles (match workbench look) ─────────────────────────── */
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

type Col = { key: string; label: string };
type Param = { name: string; type?: string; required?: boolean; default?: any; label?: string };
type Dataset = { key: string; label: string; group: string; params: Param[]; columns: Col[]; hint?: string };
type Status = { master_enabled: boolean; operate_active: boolean; openapi_configured: boolean };

export default function LingXing() {
  const [status, setStatus] = useState<Status | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [view, setView] = useState<"browse" | "auto" | "operate" | "audit">("browse");
  const [active, setActive] = useState<string>("sellers");
  const [sellers, setSellers] = useState<any[]>([]);
  const [storeSid, setStoreSid] = useState<string>("");
  const [form, setForm] = useState<Record<string, any>>({});
  const [rows, setRows] = useState<any[]>([]);
  const [meta, setMeta] = useState<{ count?: number; synced_at?: string; cached?: boolean } | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string>("");

  const ds = useMemo(() => datasets.find((d) => d.key === active), [datasets, active]);

  /* initial load */
  useEffect(() => { void boot(); }, []);
  async function boot() {
    try {
      const [st, dl] = await Promise.all([
        api.get("/lingxing/status"), api.get("/lingxing/datasets"),
      ]);
      setStatus(st.data); setDatasets(dl.data.datasets || []);
      if (st.data.master_enabled) void loadSellers();
    } catch (e: any) { setErr(humanErr(e)); }
  }
  async function loadSellers() {
    try {
      const r = await api.post("/lingxing/read/sellers", { params: {} });
      const list = r.data.rows || [];
      setSellers(list);
      if (list.length && !storeSid) setStoreSid(String(list[0].sid));
    } catch { /* master may be off */ }
  }

  async function enableMaster() {
    try {
      await api.patch("/settings", { settings: { lingxing_enabled: true } });
      await boot();
    } catch (e: any) { setErr(humanErr(e)); }
  }

  /* when dataset changes, seed the form from its param defaults + current store */
  useEffect(() => {
    if (!ds) return;
    const f: Record<string, any> = {};
    for (const p of ds.params) {
      if (p.name === "sid") f[p.name] = storeSid;
      else if (p.name === "sids") f[p.name] = storeSid;
      else f[p.name] = p.default ?? "";
    }
    setForm(f); setRows([]); setMeta(null); setErr("");
  }, [active, ds, storeSid]);

  async function run(force = false) {
    if (!ds) return;
    setLoading(true); setErr("");
    try {
      const r = await api.post(`/lingxing/read/${ds.key}`, { params: form, force });
      const data = r.data;
      setRows(Array.isArray(data.rows) ? data.rows : []);
      setMeta({ count: data.count, synced_at: data.synced_at, cached: data.cached });
    } catch (e: any) { setErr(humanErr(e)); setRows([]); setMeta(null); }
    finally { setLoading(false); }
  }

  const groups = useMemo(() => {
    const m: Record<string, Dataset[]> = {};
    for (const d of datasets) (m[d.group || "其它"] ||= []).push(d);
    return m;
  }, [datasets]);

  const cols = ds?.columns?.length ? ds.columns
    : (rows[0] ? Object.keys(rows[0]).slice(0, 8).map((k) => ({ key: k, label: k })) : []);

  return (
    <div>
      <div className="ptitle">/ 领星 ERP</div>

      {/* boot error / loading — never leave the page a dead end */}
      {!status && (
        <div className="card" style={{ padding: 12, marginBottom: 10, fontSize: 11, display: "flex", gap: 10, alignItems: "center", color: err ? "var(--red)" : "var(--t3)" }}>
          {err ? <>加载领星状态失败：{err}（后端可能未重启，新接口未生效）</> : "加载中…"}
          <span style={{ marginLeft: "auto" }}><Btn onClick={boot}>重试</Btn></span>
        </div>
      )}

      {/* status bar */}
      <div className="card" style={{ padding: "8px 12px", marginBottom: 10, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <Chip on={!!status?.openapi_configured} label={status?.openapi_configured ? "OpenAPI 已配置" : "未配置凭证"} />
        <Chip on={!!status?.master_enabled} label={status?.master_enabled ? "数据已启用" : "数据未启用"} />
        <Chip on={!!status?.operate_active} label={status?.operate_active ? "操作开关：开" : "操作开关：关(只读)"} warn={!!status?.operate_active} />
        {status && !status.master_enabled && (
          <span style={{ marginLeft: "auto" }}><Btn primary onClick={enableMaster}>启用领星数据(只读)</Btn></span>
        )}
        {status?.master_enabled && (
          <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 11, color: "var(--t3)" }}>店铺</span>
            <select value={storeSid} onChange={(e) => setStoreSid(e.target.value)} style={{ ...inputStyle, minWidth: 160 }}>
              {sellers.length === 0 && <option value="">（加载中/无）</option>}
              {sellers.map((s) => (
                <option key={s.sid} value={String(s.sid)}>{s.name || s.sid}（{s.sid}）</option>
              ))}
            </select>
          </span>
        )}
      </div>

      {!status?.master_enabled ? (
        <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--t3)", fontSize: 12 }}>
          领星数据未启用。点击上方「启用领星数据(只读)」开始浏览。<br />
          <span style={{ fontSize: 11 }}>（写操作另有独立开关 + 三重复核，默认关闭）</span>
        </div>
      ) : (
        <>
        <div style={{ display: "flex", gap: 2, marginBottom: 10 }}>
          {([["browse", "数据浏览"], ["auto", "自动化建议"], ["operate", "操作执行"], ["audit", "审计"]] as const).map(([v, l]) => (
            <button key={v} onClick={() => setView(v)} style={{
              padding: "6px 14px", fontSize: 11, border: "none", borderRadius: 4, cursor: "pointer",
              background: view === v ? "var(--acc)" : "var(--bg2)", color: view === v ? "#000" : "var(--t2)",
              fontWeight: view === v ? 600 : 400,
            }}>{l}</button>
          ))}
        </div>
        {view === "auto" ? <LingXingAutomation /> : view === "operate" ? <LingXingOperate /> : view === "audit" ? <LingXingAudit /> : (
        <div style={{ display: "flex", gap: 12 }}>
          {/* dataset list */}
          <div style={{ width: 180, flexShrink: 0 }}>
            {Object.entries(groups).map(([g, items]) => (
              <div key={g} className="card" style={{ padding: 8, marginBottom: 8 }}>
                <div style={{ fontSize: 10, color: "var(--t3)", marginBottom: 4 }}>{g}</div>
                {items.map((d) => (
                  <div key={d.key} onClick={() => setActive(d.key)} style={{
                    padding: "6px 8px", borderRadius: 4, cursor: "pointer", fontSize: 11, marginBottom: 2,
                    background: active === d.key ? "var(--acc)" : "transparent",
                    color: active === d.key ? "#000" : "var(--t2)", fontWeight: active === d.key ? 600 : 400,
                  }}>{d.label}</div>
                ))}
              </div>
            ))}
          </div>

          {/* main */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="card" style={{ padding: 12, marginBottom: 10 }}>
              {ds?.hint && <div style={{ fontSize: 11, color: "var(--t3)", marginBottom: 8 }}>{ds.hint}</div>}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
                {ds?.params.map((p) => (
                  <label key={p.name} style={{ display: "grid", gap: 3, fontSize: 10, color: "var(--t3)" }}>
                    <span>{p.label || p.name}{p.required ? " *" : ""}</span>
                    <input value={form[p.name] ?? ""} placeholder={p.type}
                      onChange={(e) => setForm((f) => ({ ...f, [p.name]: e.target.value }))}
                      style={{ ...inputStyle, width: p.type === "int" ? 90 : 150 }} />
                  </label>
                ))}
                <Btn primary onClick={() => run(false)} disabled={loading}>{loading ? "查询中…" : "查询"}</Btn>
                <Btn onClick={() => run(true)} disabled={loading}>强制刷新</Btn>
              </div>
              {err && <div style={{ marginTop: 8, fontSize: 11, color: "var(--red)" }}>{err}</div>}
              {meta && (
                <div style={{ marginTop: 8, fontSize: 10, color: "var(--t3)" }}>
                  {meta.count ?? 0} 条 · {meta.cached ? "缓存" : "实时"} · 数据时间 {fmtTs(meta.synced_at)}
                </div>
              )}
            </div>

            {/* table */}
            <div className="card" style={{ padding: 0, overflowX: "auto" }}>
              {rows.length === 0 ? (
                <div style={{ padding: 30, textAlign: "center", color: "var(--t3)", fontSize: 11 }}>
                  {loading ? "加载中…" : "暂无数据，点「查询」"}
                </div>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                  <thead>
                    <tr>{cols.map((c) => (
                      <th key={c.key} style={{ textAlign: "left", padding: "7px 10px", color: "var(--t3)", borderBottom: "1px solid var(--b)", whiteSpace: "nowrap" }}>{c.label}</th>
                    ))}</tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid var(--b)" }}>
                        {cols.map((c) => (
                          <td key={c.key} style={{ padding: "6px 10px", color: "var(--t2)", whiteSpace: "nowrap", maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis" }}>
                            {fmtCell(r[c.key])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
        )}
        </>
      )}
    </div>
  );
}

function Chip({ on, label, warn }: { on: boolean; label: string; warn?: boolean }) {
  const color = warn ? "var(--amber)" : on ? "var(--acc)" : "var(--t3)";
  return (
    <span style={{ fontSize: 11, color, display: "inline-flex", alignItems: "center", gap: 5 }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: color, display: "inline-block" }} />{label}
    </span>
  );
}
function fmtCell(v: any) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
function fmtTs(ts?: string) {
  if (!ts) return "—";
  try { return new Date(ts).toLocaleString("zh-CN", { hour12: false }); } catch { return ts; }
}
function humanErr(e: any): string {
  return e?.response?.data?.detail || e?.message || "请求失败";
}
