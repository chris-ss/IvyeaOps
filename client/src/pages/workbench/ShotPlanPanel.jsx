import { useState } from "react";
import { planImageSet, generateImage, overlayCallout } from "../../api/listing";

/**
 * AI 套图美术指导:一次规划整套主图(自适应张数,每张角度/卖点/文案/构图),
 * 先看方案可编辑 → 一键生成整套(带进度)→ 单张重做 / 改文案重叠字。
 * 自包含组件,不影响下方原有的槽位流程。
 */

const POS_OPTIONS = [
  { value: "top-left", label: "左上" }, { value: "top-center", label: "上中" }, { value: "top-right", label: "右上" },
  { value: "center", label: "居中" },
  { value: "bottom-left", label: "左下" }, { value: "bottom-center", label: "下中" }, { value: "bottom-right", label: "右下" },
];
const COUNT_OPTIONS = [
  { value: 0, label: "自适应" }, { value: 5, label: "5 张" }, { value: 6, label: "6 张" },
  { value: 7, label: "7 张" }, { value: 8, label: "8 张" },
];
const DEFAULT_SIZE = "1600x1600";
const msgOf = (e) => e?.response?.data?.detail || e?.message || "出错了";

const sel = { fontSize: 11, padding: "4px 6px", border: "1px solid var(--b)", borderRadius: 4, background: "var(--bg)", color: "var(--t)" };

function Btn({ children, onClick, primary, disabled, small }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        fontSize: small ? 10 : 11, fontWeight: 600, padding: small ? "3px 8px" : "6px 12px",
        borderRadius: 5, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
        border: primary ? "none" : "1px solid var(--b)",
        background: primary ? "var(--accent, #16a34a)" : "var(--bg)",
        color: primary ? "#fff" : "var(--t)",
      }}
    >{children}</button>
  );
}

export default function ShotPlanPanel({ projectId, colorScheme = "", notify = () => {} }) {
  const [count, setCount] = useState(0);
  const [planning, setPlanning] = useState(false);
  const [plan, setPlan] = useState(null);          // {style, product_lock, images:[...]}
  const [genAll, setGenAll] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [results, setResults] = useState({});       // slot -> {base, final, status, busy, error}

  if (!projectId) return null;

  async function doPlan() {
    setPlanning(true);
    try {
      const res = await planImageSet(projectId, { target_count: count, color_scheme: colorScheme });
      const p = res.plan || { images: [] };
      setPlan(p);
      setResults({});
      setProgress({ done: 0, total: 0 });
      notify(res.fallback ? "warn" : "success",
        res.fallback ? "已生成套图方案(AI 解析降级,可继续编辑)" : `套图方案已生成 · 共 ${p.images.length} 张`);
    } catch (e) {
      notify("error", "生成方案失败:" + msgOf(e));
    } finally { setPlanning(false); }
  }

  function editImage(idx, patch) {
    setPlan((p) => ({ ...p, images: p.images.map((im, i) => (i === idx ? { ...im, ...patch } : im)) }));
  }

  async function renderOne(img) {
    const r = await generateImage(projectId, img.render_prompt, img.slot, DEFAULT_SIZE);
    const base = r.url;
    let final = base;
    if (img.text_on_image && (img.callout || "").trim()) {
      const ov = await overlayCallout(projectId, { url: base, callout: img.callout, text_pos: img.text_pos });
      final = ov.url;
    }
    return { base, final };
  }

  async function genAllImages() {
    if (!plan?.images?.length) return;
    setGenAll(true);
    setProgress({ done: 0, total: plan.images.length });
    for (let i = 0; i < plan.images.length; i++) {
      const img = plan.images[i];
      setResults((r) => ({ ...r, [img.slot]: { ...(r[img.slot] || {}), status: "running" } }));
      try {
        const out = await renderOne(img);
        setResults((r) => ({ ...r, [img.slot]: { ...out, status: "done" } }));
      } catch (e) {
        setResults((r) => ({ ...r, [img.slot]: { status: "error", error: msgOf(e) } }));
      }
      setProgress((p) => ({ ...p, done: i + 1 }));
    }
    setGenAll(false);
    notify("success", "整套已生成完成");
  }

  async function redoOne(idx) {
    const img = plan.images[idx];
    setResults((r) => ({ ...r, [img.slot]: { ...(r[img.slot] || {}), status: "running" } }));
    try {
      const out = await renderOne(img);
      setResults((r) => ({ ...r, [img.slot]: { ...out, status: "done" } }));
    } catch (e) {
      setResults((r) => ({ ...r, [img.slot]: { status: "error", error: msgOf(e) } }));
      notify("error", "重做失败:" + msgOf(e));
    }
  }

  // 改文案/位置后只重叠字,不重渲染(省时省钱)
  async function reapplyText(idx) {
    const img = plan.images[idx];
    const cur = results[img.slot];
    if (!cur?.base) { notify("warn", "请先生成这张图,再调整文案"); return; }
    if (!img.text_on_image || !(img.callout || "").trim()) {
      setResults((r) => ({ ...r, [img.slot]: { ...cur, final: cur.base } }));
      return;
    }
    setResults((r) => ({ ...r, [img.slot]: { ...cur, busy: true } }));
    try {
      const ov = await overlayCallout(projectId, { url: cur.base, callout: img.callout, text_pos: img.text_pos });
      setResults((r) => ({ ...r, [img.slot]: { ...cur, final: ov.url, busy: false } }));
    } catch (e) {
      setResults((r) => ({ ...r, [img.slot]: { ...cur, busy: false } }));
      notify("error", "叠字失败:" + msgOf(e));
    }
  }

  const busy = planning || genAll;
  const pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;

  return (
    <div className="card" style={{ padding: 12, marginBottom: 12, borderLeft: "3px solid var(--accent, #16a34a)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 700 }}>✨ AI 套图美术指导</span>
        <span style={{ fontSize: 10, color: "var(--t3)" }}>
          一次规划整套主图:自动定角度 / 卖点 / 文案 / 构图,文字独立清晰排版
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <span style={{ fontSize: 10, fontWeight: 600 }}>张数</span>
        <select value={count} onChange={(e) => setCount(Number(e.target.value))} style={sel} disabled={busy}>
          {COUNT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <Btn onClick={doPlan} primary disabled={busy}>{planning ? "AI 策划中…" : (plan ? "重新规划方案" : "一键生成套图方案")}</Btn>
        {plan?.images?.length > 0 && (
          <Btn onClick={genAllImages} primary disabled={busy}>
            {genAll ? `生成中 ${progress.done}/${progress.total}` : `生成整套(${plan.images.length} 张)`}
          </Btn>
        )}
        {plan?.style?.palette && (
          <span style={{ fontSize: 10, color: "var(--t3)" }}>风格:{plan.style.palette}{plan.style.mood ? ` · ${plan.style.mood}` : ""}</span>
        )}
      </div>

      {genAll && (
        <div style={{ height: 5, background: "var(--bg2)", borderRadius: 3, overflow: "hidden", marginBottom: 10 }}>
          <div style={{ width: `${pct}%`, height: "100%", background: "var(--accent, #16a34a)", transition: "width .3s" }} />
        </div>
      )}

      {!plan && (
        <div style={{ fontSize: 10, color: "var(--t3)", lineHeight: 1.7 }}>
          先在上方完成抓取 / 产品信息 / 视觉分析 / 文案,再点「一键生成套图方案」。AI 会把这套图当成一个整体来策划——
          主图干净无字、每张副图解决一个不同的购买顾虑,文字用真实文案逐字排版(不靠模型画字,不糊不错字)。
        </div>
      )}

      {plan?.images?.map((img, idx) => {
        const res = results[img.slot] || {};
        return (
          <div key={img.slot} style={{ display: "flex", gap: 10, padding: 10, marginTop: 8, border: "1px solid var(--b)", borderRadius: 6, background: "var(--bg2)" }}>
            {/* preview */}
            <div style={{ width: 120, height: 120, flexShrink: 0, borderRadius: 5, overflow: "hidden", background: "var(--bg)", border: "1px solid var(--b)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "var(--t3)", textAlign: "center", position: "relative" }}>
              {res.final ? (
                <img src={res.final} alt={img.role} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              ) : res.status === "running" ? "生成中…" : res.status === "error" ? <span style={{ color: "#dc2626" }}>失败<br />{res.error}</span> : `第 ${idx + 1} 张\n${img.role}`}
            </div>
            {/* spec + edit */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4, flexWrap: "wrap" }}>
                <span style={{ fontSize: 11, fontWeight: 700, padding: "1px 7px", borderRadius: 10, background: "var(--accent, #16a34a)", color: "#fff" }}>{img.role}</span>
                <span style={{ fontSize: 10, color: "var(--t3)" }}>{[img.angle, img.scene].filter(Boolean).join(" · ")}</span>
              </div>
              {img.selling_point && <div style={{ fontSize: 10, color: "var(--t2)", marginBottom: 4 }}>卖点:{img.selling_point}</div>}
              {img.composition && <div style={{ fontSize: 10, color: "var(--t3)", marginBottom: 6 }}>构图:{img.composition}</div>}
              {img.slot !== "main" && (
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <label style={{ fontSize: 10, display: "flex", alignItems: "center", gap: 3 }}>
                    <input type="checkbox" checked={!!img.text_on_image} onChange={(e) => editImage(idx, { text_on_image: e.target.checked })} />上文字
                  </label>
                  <input
                    value={img.callout || ""} onChange={(e) => editImage(idx, { callout: e.target.value })}
                    placeholder="卖点文案(逐字排版上图)" disabled={!img.text_on_image}
                    style={{ ...sel, flex: 1, minWidth: 120, opacity: img.text_on_image ? 1 : 0.5 }}
                  />
                  <select value={img.text_pos || "bottom-center"} onChange={(e) => editImage(idx, { text_pos: e.target.value })} style={sel} disabled={!img.text_on_image}>
                    {POS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
              )}
              <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                <Btn small onClick={() => redoOne(idx)} disabled={busy || res.status === "running"}>{res.final ? "重做这张" : "生成这张"}</Btn>
                {res.base && img.slot !== "main" && (
                  <Btn small onClick={() => reapplyText(idx)} disabled={res.busy}>{res.busy ? "叠字中…" : "应用文案"}</Btn>
                )}
                {res.final && <a href={res.final} download style={{ fontSize: 10, fontWeight: 600, padding: "3px 8px", border: "1px solid var(--b)", borderRadius: 5, textDecoration: "none", color: "var(--t)" }}>下载</a>}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
