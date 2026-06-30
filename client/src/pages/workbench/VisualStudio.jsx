import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, Check, ChevronDown, Download, Image as ImageIcon,
  Layers3, Loader2, RefreshCw, ShieldCheck, Sparkles, WandSparkles,
} from "lucide-react";
import {
  generateImage, planImageSet,
  reviewImageSet, reviewRender, saveCreativeSet,
} from "../../api/listing";

const SHOT_LABELS = {
  white_main: "白底主图",
  hero_feature: "核心利益",
  lifestyle: "真实使用",
  detail: "细节特写",
  comparison: "对比证明",
  specs: "规格 / 兼容",
  in_box: "包装清单",
  trust: "信任收口",
  aplus_banner: "A+ 品牌首屏",
};
const ZONES = [
  ["top-left", "左上"], ["top-center", "上中"], ["top-right", "右上"],
  ["center-left", "左中"], ["center-right", "右中"],
  ["bottom-left", "左下"], ["bottom-center", "下中"], ["bottom-right", "右下"],
];
const LAYOUTS = [
  ["editorial", "编辑式留白"], ["minimal", "极简无底"], ["split", "分栏版式"],
  ["proof", "数据证明"], ["grid", "信息网格"],
];
const TONES = [
  ["natural", "自然实拍"], ["studio", "克制棚拍"], ["editorial", "品牌编辑感"],
];
const LANGUAGES = [
  ["en", "English"], ["de", "Deutsch"], ["fr", "Français"], ["es", "Español"],
  ["it", "Italiano"], ["ja", "日本語"], ["zh", "中文"],
];
const messageOf = (error) => error?.response?.data?.detail || error?.message || "操作失败";
const INTERNAL_COPY_RE = /approved copy|approved title|product facts?|claims?|image should|do not fabricate|source material|evidence|supported by|supports? (?:the|this)/i;
const assetUrl = (asset) => typeof asset === "string" ? asset : asset?.url;
const safeProof = (value) => {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length <= 24 && /\d/.test(text) && !INTERNAL_COPY_RE.test(text) ? text : "";
};

function normalizeSets(value) {
  if (!value || typeof value !== "object") return {};
  return value;
}

function nowVersion(image) {
  if (!image?.final_url) return null;
  return {
    url: image.final_url,
    base_url: image.base_url || "",
    render_qa: image.render_qa || null,
    created_at: new Date().toISOString(),
  };
}

function Pill({ tone = "neutral", children }) {
  return <span className={`vs-pill vs-pill-${tone}`}>{children}</span>;
}

function QualitySummary({ quality }) {
  const score = Number(quality?.score ?? 0);
  const issues = quality?.issues || [];
  const errors = issues.filter((item) => item.severity === "error").length;
  return (
    <div className={`vs-quality ${errors ? "has-error" : "is-ready"}`}>
      <div className="vs-quality-score">{score}</div>
      <div>
        <div className="vs-quality-title">策略质检</div>
        <div className="vs-quality-copy">
          {errors ? `${errors} 项阻塞问题` : issues.length ? `${issues.length} 项建议` : "结构与文案检查通过"}
        </div>
      </div>
    </div>
  );
}

export default function VisualStudio({
  projectId,
  initialSets = {},
  sourceAssets = [],
  contextStatus = {},
  colorScheme = "",
  notify = () => {},
  onSetsChange = () => {},
}) {
  const [deliverable, setDeliverable] = useState("gallery");
  const [sets, setSets] = useState(() => normalizeSets(initialSets));
  const [count, setCount] = useState(7);
  const [visualTone, setVisualTone] = useState("natural");
  const [language, setLanguage] = useState("en");
  const [brief, setBrief] = useState("");
  const [planning, setPlanning] = useState(false);
  const [generatingAll, setGeneratingAll] = useState(false);
  const [jobs, setJobs] = useState({});
  const [selected, setSelected] = useState(0);
  const [preview, setPreview] = useState("");
  const [exporting, setExporting] = useState(false);
  const lastPublishedRef = useRef(null);

  useEffect(() => {
    // Parent state echoes every studio edit back through initialSets. Do not
    // treat that echo as a project reload or the selected card would jump to #1.
    if (initialSets === lastPublishedRef.current) {
      lastPublishedRef.current = null;
      return;
    }
    const incoming = normalizeSets(initialSets);
    setSets(incoming);
    setBrief(incoming[deliverable]?.creative_brief || "");
    setLanguage(incoming[deliverable]?.language || "en");
    setSelected(0);
    setJobs({});
  }, [projectId, initialSets]);

  useEffect(() => {
    const existing = sets[deliverable]?.images?.length;
    setCount(existing || (deliverable === "aplus" ? 5 : 7));
    setBrief(sets[deliverable]?.creative_brief || "");
    setLanguage(sets[deliverable]?.language || "en");
    setSelected(0);
  }, [deliverable]); // eslint-disable-line react-hooks/exhaustive-deps

  const plan = sets[deliverable] || null;
  const images = plan?.images || [];
  const active = images[selected] || null;
  const verifiedProduct = sourceAssets.find((asset) => asset?.white_ready === true);
  const replacementAssets = sourceAssets.filter((asset) => asset?.kind === "uploaded" && asset?.white_ready === true);
  const autoProductSource = plan?.product_source_url || assetUrl(verifiedProduct) || "";
  const activeBoundSource = active?.product_source_url || autoProductSource;
  const activeRenderBlocked = !!active && !activeBoundSource;
  const completed = images.filter((item) => item.final_url).length;
  const reviewed = images.filter((item) => item.final_url && item.human_reviewed).length;
  const qaPassed = images.filter((item) => item.final_url && item.render_qa?.ready).length;
  const blocked = images.filter((item) => !(item.product_source_url || autoProductSource)).length;
  const canDeliver = images.length > 0 && reviewed === images.length && qaPassed === images.length
    && !blocked && plan?.quality?.ready !== false && plan?.set_qa?.ready === true;
  const busy = planning || generatingAll || Object.values(jobs).some((job) => job === "running");

  const styleLine = useMemo(() => {
    if (!plan?.style) return "";
    return [plan.style.direction, plan.style.palette, plan.style.lighting].filter(Boolean).join(" · ");
  }, [plan]);

  function publishSets(next) {
    lastPublishedRef.current = next;
    setSets(next);
    onSetsChange(next);
  }

  async function persist(nextPlan) {
    const nextSets = { ...sets, [deliverable]: nextPlan };
    publishSets(nextSets);
    try {
      const response = await saveCreativeSet(projectId, deliverable, nextPlan);
      if (response?.plan) {
        const saved = { ...nextSets, [deliverable]: response.plan };
        publishSets(saved);
        return response.plan;
      }
    } catch (error) {
      notify("error", `保存分镜失败：${messageOf(error)}`);
    }
    return nextPlan;
  }

  function patchImage(index, patch) {
    if (!plan) return;
    const next = { ...plan, images: images.map((item, i) => (i === index ? { ...item, ...patch } : item)) };
    publishSets({ ...sets, [deliverable]: next });
  }

  async function saveImageEdit(index, patch = {}) {
    if (!plan) return;
    const reviewOnly = Object.keys(patch).every((key) => key === "human_reviewed");
    const invalidatesRender = Object.keys(patch).some((key) => [
      "eyebrow", "headline", "callout", "supporting_text", "proof", "text_on_image",
      "text_zone", "text_pos", "layout_style", "render_prompt", "size",
    ].includes(key));
    const next = {
      ...plan,
      set_qa: reviewOnly ? plan.set_qa : null,
      images: images.map((item, i) => {
        if (i !== index) return item;
        const updated = { ...item, ...patch };
        if (!invalidatesRender || !item.final_url) return updated;
        const previous = nowVersion(item);
        return {
          ...updated,
          base_url: "",
          final_url: "",
          render_qa: null,
          human_reviewed: false,
          versions: [...(item.versions || []), ...(previous ? [previous] : [])].slice(-8),
        };
      }),
    };
    await persist(next);
  }

  async function createPlan() {
    setPlanning(true);
    try {
      const response = await planImageSet(projectId, {
        target_count: count,
        color_scheme: colorScheme === "auto" ? "" : colorScheme,
        deliverable,
        visual_tone: visualTone,
        language,
        brief,
      });
      const next = { ...sets, [deliverable]: response.plan };
      publishSets(next);
      setSelected(0);
      notify(response.fallback ? "warn" : "success", response.fallback
        ? "AI 策划暂不可用，已生成可编辑的稳健方案"
        : `${deliverable === "aplus" ? "A+" : "商品套图"}方案已生成，共 ${response.plan.images.length} 张`);
    } catch (error) {
      notify("error", `策划失败：${messageOf(error)}`);
    } finally {
      setPlanning(false);
    }
  }

  async function reviewFinal(image, finalUrl, sourceUrl = "", productProfile = plan?.product_profile) {
    return reviewRender(projectId, {
      url: finalUrl,
      size: image.size || (deliverable === "aplus" ? "1464x600" : "1600x1600"),
      slot: image.slot,
      role: image.role,
      shot_type: image.shot_type,
      layout_blueprint: image.layout_blueprint || "",
      eyebrow: image.eyebrow || "",
      headline: image.headline || "",
      callout: image.callout || "",
      supporting_text: image.supporting_text || "",
      proof: safeProof(image.proof),
      source_url: sourceUrl || image.source_url || "",
      show_product: image.show_product !== false,
      product_fidelity_anchors: productProfile?.fidelity_anchors || [],
    });
  }

  async function renderOne(index, workingPlan = plan, silent = false) {
    const image = workingPlan?.images?.[index];
    if (!image) return workingPlan;
    const productSource = image.product_source_url || workingPlan.product_source_url
      || assetUrl(verifiedProduct) || "";
    if (!productSource) {
      if (!silent) notify("warn", `「${image.role}」未找到产品真值素材，请先上传产品图或采集可用主图`);
      return workingPlan;
    }
    setJobs((prev) => ({ ...prev, [image.slot]: "running" }));
    try {
      const size = image.size || (deliverable === "aplus" ? "1464x600" : "1600x1600");
      const generated = await generateImage(
        projectId,
        image.render_prompt,
        image.slot,
        size,
        true,
        [productSource],
        "product",
      );
      let baseUrl = generated.url || generated.imageUrl;
      let finalUrl = baseUrl;
      let renderQa = await reviewFinal(image, finalUrl, productSource, workingPlan.product_profile);
      const generatedHistory = [];
      let autoRetryCount = 0;
      const retryGuidance = (renderQa.retry_guidance || []).filter(Boolean).slice(0, 6);
      if (!renderQa.ready && retryGuidance.length) {
        autoRetryCount = 1;
        const retryPrompt = `${image.render_prompt}\n\nMANDATORY QA REVISION — this is the single repair attempt. `
          + "Keep the original buyer question and art direction, but correct every issue below. Reference image 1 remains the only immutable product truth. "
          + "Do not solve a fidelity issue by hiding, cropping away, redesigning or replacing the product.\n- "
          + retryGuidance.join("\n- ");
        const retried = await generateImage(
          projectId,
          retryPrompt,
          `${image.slot}_qa_retry`,
          size,
          true,
          [productSource],
          "product",
        );
        const retryBaseUrl = retried.url || retried.imageUrl;
        const retryFinalUrl = retryBaseUrl;
        const retryQa = await reviewFinal(image, retryFinalUrl, productSource, workingPlan.product_profile);
        const useRetry = retryQa.ready || Number(retryQa.score || 0) >= Number(renderQa.score || 0);
        if (useRetry) {
          generatedHistory.push({ url: finalUrl, base_url: baseUrl, render_qa: renderQa, created_at: new Date().toISOString() });
          baseUrl = retryBaseUrl;
          finalUrl = retryFinalUrl;
          renderQa = retryQa;
        } else {
          generatedHistory.push({ url: retryFinalUrl, base_url: retryBaseUrl, render_qa: retryQa, created_at: new Date().toISOString() });
        }
      }
      const oldVersion = nowVersion(image);
      const versions = [
        ...(image.versions || []), ...(oldVersion ? [oldVersion] : []), ...generatedHistory,
      ].slice(-8);
      const nextImage = {
        ...image,
        asset_mode: "generate",
        show_product: true,
        requires_source: false,
        source_url: "",
        product_source_url: productSource,
        template_url: "",
        layout_blueprint: "",
        base_url: baseUrl,
        final_url: finalUrl,
        render_qa: renderQa,
        auto_retry_count: autoRetryCount,
        last_retry_guidance: retryGuidance,
        versions,
        human_reviewed: false,
      };
      const nextPlan = {
        ...workingPlan,
        set_qa: null,
        images: workingPlan.images.map((item, i) => (i === index ? nextImage : item)),
      };
      publishSets({ ...sets, [deliverable]: nextPlan });
      setJobs((prev) => ({ ...prev, [image.slot]: renderQa.ready ? "done" : "error" }));
      if (!silent) notify(renderQa.ready ? "success" : "warn", renderQa.ready
        ? renderQa.manual_visual_review_required
          ? `第 ${index + 1} 张硬规则通过；远程审美复核未返回，请严格人工复核`
          : `第 ${index + 1} 张已通过成图质检，请核对产品一致性`
        : autoRetryCount
          ? `第 ${index + 1} 张已按质检意见自动重画一次，仍未通过硬门槛`
          : `第 ${index + 1} 张已生成，但成图质检未通过`);
      return nextPlan;
    } catch (error) {
      setJobs((prev) => ({ ...prev, [image.slot]: "error" }));
      if (!silent) notify("error", `生成失败：${messageOf(error)}`);
      return workingPlan;
    }
  }

  async function renderAll() {
    if (!plan?.images?.length) return;
    setGeneratingAll(true);
    let working = plan;
    let success = 0;
    for (let index = 0; index < working.images.length; index += 1) {
      const before = working.images[index]?.final_url;
      working = await renderOne(index, working, true);
      if (working.images[index]?.final_url && working.images[index]?.final_url !== before) success += 1;
      // Image generation is slow. Persist after each completed card so a refresh
      // or a later-card failure never loses the work already paid for.
      if (working.images[index]?.final_url !== before) working = await persist(working);
    }
    if (working.images.length && working.images.every((item) => item.final_url && item.render_qa?.ready)) {
      try {
        const setReview = await reviewImageSet(projectId, deliverable);
        if (setReview?.plan) {
          working = setReview.plan;
          publishSets({ ...sets, [deliverable]: working });
        }
      } catch (error) {
        notify("warn", `整套质检失败：${messageOf(error)}`);
      }
    }
    setGeneratingAll(false);
    const setReady = working?.set_qa?.ready;
    notify(setReady ? "success" : "warn", setReady
      ? `已处理 ${success} 张，单图与整套质检均通过`
      : success ? `已处理 ${success} 张；未通过的单图或整套设计已标记为阻塞`
        : "没有生成图片，请检查真实素材要求或生成服务");
  }

  async function redoOne(index) {
    const next = await renderOne(index, plan, false);
    if (next) await persist(next);
  }

  async function reviewWholeSet() {
    if (!images.length || !images.every((item) => item.final_url && item.render_qa?.ready)) {
      return notify("warn", "请先让每张图片通过单图质检");
    }
    setGeneratingAll(true);
    try {
      const response = await reviewImageSet(projectId, deliverable);
      if (response?.plan) publishSets({ ...sets, [deliverable]: response.plan });
      notify(response?.set_qa?.ready ? "success" : "warn", response?.set_qa?.ready
        ? "整套设计一致性与叙事质检通过"
        : `整套质检未通过：${response?.set_qa?.issues?.[0]?.message || "请查看质检结果"}`);
    } catch (error) {
      notify("error", `整套质检失败：${messageOf(error)}`);
    } finally {
      setGeneratingAll(false);
    }
  }

  async function useSourceAsset(url) {
    if (!active || !url) return;
    try {
      const staged = {
        ...plan,
        product_source_url: url,
        images: images.map((item) => ({
          ...item,
          asset_mode: "generate",
          show_product: true,
          requires_source: false,
          source_url: "",
          product_source_url: url,
          template_url: "",
          layout_blueprint: "",
          render_qa: null,
          human_reviewed: false,
        })),
      };
      await persist(staged);
      notify("success", "已更换整套产品真值图；后续生成只允许改变场景、镜头、构图和光线");
    } catch (error) {
      setJobs((prev) => ({ ...prev, [active.slot]: "error" }));
      notify("error", `真实素材处理失败：${messageOf(error)}`);
    }
  }

  async function restoreVersion(versionIndex) {
    const image = active;
    const version = image?.versions?.[versionIndex];
    if (!version) return;
    const current = nowVersion(image);
    const versions = image.versions.filter((_, index) => index !== versionIndex);
    if (current) versions.push(current);
    await saveImageEdit(selected, {
      final_url: version.url,
      base_url: version.base_url || image.base_url,
      render_qa: version.render_qa || null,
      versions: versions.slice(-8),
      human_reviewed: false,
    });
  }

  async function downloadSet() {
    const readyImages = images.filter((image) => image.final_url);
    if (!readyImages.length) return;
    setExporting(true);
    try {
      const { default: JSZip } = await import("jszip");
      const zip = new JSZip();
      for (let index = 0; index < readyImages.length; index += 1) {
        const image = readyImages[index];
        const response = await fetch(image.final_url, { credentials: "include" });
        if (!response.ok) throw new Error(`第 ${index + 1} 张下载失败`);
        const blob = await response.blob();
        const extension = blob.type.includes("jpeg") ? "jpg" : blob.type.includes("webp") ? "webp" : "png";
        const role = String(image.role || image.slot).replace(/[\\/:*?"<>|]/g, "-");
        const draft = image.human_reviewed ? "" : "_DRAFT";
        zip.file(`${String(index + 1).padStart(2, "0")}_${role}${draft}.${extension}`, blob);
      }
      zip.file("review-manifest.json", JSON.stringify({
        project_id: projectId,
        deliverable,
        exported_at: new Date().toISOString(),
        commercially_reviewed: canDeliver,
        images: readyImages.map((image, index) => ({
          order: index + 1,
          slot: image.slot,
          role: image.role,
          human_reviewed: !!image.human_reviewed,
          evidence: image.evidence || "",
        })),
      }, null, 2));
      const archive = await zip.generateAsync({ type: "blob" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(archive);
      link.download = `${projectId}_${deliverable}_${canDeliver ? "reviewed" : "draft"}.zip`;
      link.click();
      URL.revokeObjectURL(link.href);
      if (!canDeliver) notify("warn", "已导出草稿包；未人工复核的图片文件名带 DRAFT");
    } catch (error) {
      notify("error", `整套导出失败：${messageOf(error)}`);
    } finally {
      setExporting(false);
    }
  }

  if (!projectId) return null;

  return (
    <section className={`visual-studio ${deliverable === "aplus" ? "vs-aplus" : "vs-gallery"}`}>
      <header className="vs-header">
        <div>
          <div className="vs-kicker"><Sparkles size={14} /> Listing Visual Studio</div>
          <h2>一张白底图，直出整套品牌视觉</h2>
          <p>自动吸收采集洞察与 Listing 文案；产品、场景、设计和文字均由图片模型一次生成。</p>
        </div>
        {plan && <QualitySummary quality={plan.quality} />}
      </header>

      <div className="vs-input-foundation">
        <div className="vs-context-sources">
          <div><span>生成依据</span><strong>前两步内容自动接入</strong></div>
          <Pill tone={contextStatus.whiteReady || verifiedProduct ? "success" : "warning"}>
            {contextStatus.whiteReady || verifiedProduct ? "白底产品图已就绪" : "缺少白底产品图"}
          </Pill>
          <Pill tone={contextStatus.scrapedReady ? "success" : "warning"}>采集资料{contextStatus.scrapedReady ? "已接入" : "待补充"}</Pill>
          <Pill tone={contextStatus.analysisReady ? "success" : "warning"}>AI 洞察{contextStatus.analysisReady ? "已接入" : "待生成"}</Pill>
          <Pill tone={contextStatus.copyReady ? "success" : "warning"}>Listing 文案{contextStatus.copyReady ? "已接入" : "待生成"}</Pill>
        </div>
        <label className="vs-manual-brief">
          <span><strong>手动创意需求</strong><em>优先于自动风格建议，但不覆盖产品真值和事实合规</em></span>
          <textarea value={brief} onChange={(event) => setBrief(event.target.value)} rows={3}
            placeholder="例如：面向注重品质的户外家庭；使用森林绿与暖米色；避免科技蓝；第 4 张必须强调快速安装；整体像成熟欧美户外品牌。" disabled={busy} />
        </label>
      </div>

      <div className="vs-toolbar">
        <div className="vs-segment" aria-label="交付物类型">
          <button className={deliverable === "gallery" ? "active" : ""} onClick={() => setDeliverable("gallery")}>
            <ImageIcon size={14} /> 商品套图
          </button>
          <button className={deliverable === "aplus" ? "active" : ""} onClick={() => setDeliverable("aplus")}>
            <Layers3 size={14} /> A+ 模块
          </button>
        </div>
        <label className="vs-compact-field">
          <span>张数</span>
          <select value={count} onChange={(event) => setCount(Number(event.target.value))} disabled={busy}>
            {(deliverable === "aplus" ? [4, 5, 6] : [5, 6, 7, 8]).map((value) => <option key={value} value={value}>{value} 张</option>)}
          </select>
        </label>
        <label className="vs-compact-field">
          <span>视觉基调</span>
          <select value={visualTone} onChange={(event) => setVisualTone(event.target.value)} disabled={busy}>
            {TONES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="vs-compact-field">
          <span>图上语言</span>
          <select value={language} onChange={(event) => setLanguage(event.target.value)} disabled={busy}>
            {LANGUAGES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <button className="vs-button secondary" onClick={createPlan} disabled={busy}>
          {planning ? <><Loader2 className="spin" size={14} /> 策划中</> : <><WandSparkles size={14} /> {plan ? "重新策划" : "生成整套方案"}</>}
        </button>
        {plan && (
          <button className="vs-button primary" onClick={renderAll} disabled={busy}>
            {generatingAll ? <><Loader2 className="spin" size={14} /> 生成中 {completed}/{images.length}</> : <><Sparkles size={14} /> 一键生成整套</>}
          </button>
        )}
        {completed > 0 && (
          <button className="vs-button secondary" onClick={reviewWholeSet}
            disabled={busy || completed !== images.length || qaPassed !== images.length}>
            <ShieldCheck size={14} /> 复核整套
          </button>
        )}
        {completed > 0 && (
          <button className="vs-button secondary" onClick={downloadSet} disabled={busy || exporting}>
            {exporting ? <><Loader2 className="spin" size={14} /> 打包中</> : <><Download size={14} /> 下载整套</>}
          </button>
        )}
      </div>

      {!plan ? (
        <div className="vs-empty">
          <div className="vs-empty-icon"><Layers3 size={28} /></div>
          <h3>先编译整套图文提示词</h3>
          <p>系统会锁定白底产品真值、统一色板与设计语言，再把每张图的场景、排版和精确文案编译成最终生图指令。</p>
          <div className="vs-empty-flow">
            <span>白底真值 + 前两步内容</span><b>→</b><span>整套提示词</span><b>→</b><span>图文一次直出</span><b>→</b><span>OCR 与视觉复核</span>
          </div>
        </div>
      ) : (
        <>
          <div className="vs-strategy-strip">
            <div><span>套图叙事</span><strong>{plan.story || "按购买决策顺序逐张解决疑虑"}</strong></div>
            <div><span>产品视觉身份</span><strong>{[
              plan.product_profile?.category_family, plan.product_profile?.object_behavior,
            ].filter(Boolean).join(" · ") || "已按产品形态与材质分析"}</strong></div>
            <div><span>美术与统一色系</span><strong>{styleLine || "产品定制、整套统一"}</strong></div>
            <div className="vs-delivery-state">
              <span>交付状态</span>
              <strong className={canDeliver ? "ready" : "pending"}>
                {canDeliver ? <><ShieldCheck size={14} /> 可交付</> : <><AlertTriangle size={14} /> 单图 {qaPassed}/{images.length} · 整套 {plan?.set_qa?.ready ? "通过" : "待通过"} · 人审 {reviewed}/{images.length}</>}
              </strong>
            </div>
          </div>

          {(plan.quality?.issues || []).length > 0 && (
            <details className="vs-issues">
              <summary><AlertTriangle size={14} /> 策略质检发现 {plan.quality.issues.length} 项 <ChevronDown size={14} /></summary>
              <div>
                {plan.quality.issues.map((issue, index) => (
                  <p key={`${issue.code}-${index}`} className={issue.severity === "error" ? "error" : "warning"}>
                    {issue.severity === "error" ? "阻塞" : "建议"} · {issue.message}
                  </p>
                ))}
              </div>
            </details>
          )}

          {(plan.set_qa?.issues || []).length > 0 && (
            <details className="vs-issues" open>
              <summary><AlertTriangle size={14} /> 整套质检未通过 <ChevronDown size={14} /></summary>
              <div>{plan.set_qa.issues.map((issue, index) => (
                <p key={`${issue.code}-${index}`} className="error">阻塞 · {issue.message}</p>
              ))}</div>
            </details>
          )}

          <div className="vs-workspace">
            <div className="vs-board">
              <div className="vs-board-head">
                <div>
                  <h3>套图分镜</h3>
                  <p>{completed}/{images.length} 已处理 · {qaPassed}/{images.length} 成图质检通过 · {reviewed}/{images.length} 已人工复核{blocked ? ` · ${blocked} 张待产品真值` : ""}</p>
                </div>
              </div>
              <div className="vs-story-grid">
                {images.map((image, index) => {
                  const running = jobs[image.slot] === "running";
                  const cardSourceBound = !!(image.product_source_url || autoProductSource);
                  const cardBlocked = !cardSourceBound;
                  return (
                    <article key={image.slot} className={`vs-shot-card ${selected === index ? "selected" : ""}`}
                      onClick={() => setSelected(index)}>
                      <div className="vs-shot-preview" onDoubleClick={() => image.final_url && setPreview(image.final_url)}>
                        {image.final_url ? <img src={image.final_url} alt={image.role} /> : (
                          <div className="vs-shot-placeholder">
                            {running ? <Loader2 className="spin" size={20} /> : cardBlocked
                              ? <AlertTriangle size={20} /> : <ImageIcon size={20} />}
                            {!running && cardSourceBound && <small>产品真值已绑定 · 尚未生成</small>}
                          </div>
                        )}
                        <span className="vs-shot-number">{String(index + 1).padStart(2, "0")}</span>
                        {image.human_reviewed && <span className="vs-reviewed"><Check size={11} /> 已核对</span>}
                      </div>
                      <div className="vs-shot-body">
                        <div className="vs-shot-title"><strong>{image.role}</strong><Pill>{SHOT_LABELS[image.shot_type] || image.shot_type}</Pill></div>
                        <p>{image.buyer_question || image.selling_point || "待补充购买问题"}</p>
                        <div className="vs-card-meta">
                          <Pill tone="success">图文模型直出</Pill>
                          <Pill tone={cardSourceBound ? "success" : "warning"}>{cardSourceBound ? "产品真值已绑定" : "缺少产品真值"}</Pill>
                          {image.final_url && image.render_qa?.ready && <Pill tone="success">{image.render_qa.manual_visual_review_required ? "硬规则通过" : "成图质检通过"}</Pill>}
                          {image.final_url && !image.render_qa?.ready && <Pill tone="warning">成图被拦截</Pill>}
                          {image.final_url && !image.human_reviewed && <Pill tone="warning">待核对产品</Pill>}
                          {image.final_url && image.human_reviewed && <Pill tone="success">可交付</Pill>}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>

            {active && (
              <aside className="vs-inspector">
                <div className="vs-inspector-head">
                  <div>
                    <span>分镜 {selected + 1} / {images.length}</span>
                    <h3>{active.role}</h3>
                  </div>
                  <Pill>{SHOT_LABELS[active.shot_type] || active.shot_type}</Pill>
                </div>

                <div className="vs-inspector-actions">
                  <button className="vs-button primary" onClick={() => redoOne(selected)} disabled={busy || activeRenderBlocked}>
                    {jobs[active.slot] === "running" ? <><Loader2 className="spin" size={14} /> 处理中</> : active.final_url
                      ? <><RefreshCw size={14} /> 重做这张</> : <><Sparkles size={14} /> 图文直出</>}
                  </button>
                  {active.final_url && <a className="vs-icon-button" href={active.final_url} download title="下载"><Download size={15} /></a>}
                </div>

                <div className={`vs-source-warning ${activeRenderBlocked ? "is-missing" : "is-bound"}`}>
                    {activeRenderBlocked ? <AlertTriangle size={16} /> : <Check size={16} />}
                    <div>
                      <strong>{activeRenderBlocked ? "缺少产品真值素材" : "已锁定产品真值 · 模型整图直出"}</strong>
                      <p>系统优先使用上传白底图，否则使用通过检测的采集主图。模型一次生成产品、场景、设计与文字；产品外形、比例、颜色、材质、Logo、接口、配件和数量必须不变。</p>
                      <div className="vs-bound-assets">
                        {activeBoundSource && <figure><img src={activeBoundSource} alt="自动绑定产品素材" /><figcaption>不可变产品真值</figcaption></figure>}
                      </div>
                      {replacementAssets.length > 0 && (
                        <details className="vs-source-replace">
                          <summary>更换整套产品真值图</summary>
                          <div className="vs-source-assets">
                            {replacementAssets.map((asset, index) => {
                              const url = assetUrl(asset);
                              return <button key={`${url}-${index}`} className={activeBoundSource === url ? "selected" : ""}
                                onClick={() => useSourceAsset(url)} title="使用这张素材">
                                <img src={url} alt="候选素材" />
                              </button>;
                            })}
                          </div>
                        </details>
                      )}
                    </div>
                </div>

                <div className="vs-form-section">
                  <h4>销售任务与证据</h4>
                  <label><span>购买者的问题</span><textarea value={active.buyer_question || ""} rows={2}
                    onChange={(event) => patchImage(selected, { buyer_question: event.target.value })}
                    onBlur={(event) => saveImageEdit(selected, { buyer_question: event.target.value })} /></label>
                  <label><span>卖点依据</span><textarea value={active.evidence || ""} rows={2}
                    onChange={(event) => patchImage(selected, { evidence: event.target.value })}
                    onBlur={(event) => saveImageEdit(selected, { evidence: event.target.value })} /></label>
                </div>

                {active.shot_type !== "white_main" && (
                  <div className="vs-form-section">
                    <div className="vs-section-title"><h4>图上文案 · 图片模型直出</h4><label className="vs-switch"><input type="checkbox" checked={!!active.text_on_image}
                      onChange={(event) => saveImageEdit(selected, { text_on_image: event.target.checked })} /><span />上文字</label></div>
                    <p className="vs-copy-note">修改任一文字或版式后，当前成图会进入历史版本，需要重新生成。</p>
                    <label><span>眉题（可选）</span><input value={active.eyebrow || ""} maxLength={20}
                      onChange={(event) => patchImage(selected, { eyebrow: event.target.value })}
                      onBlur={(event) => saveImageEdit(selected, { eyebrow: event.target.value })} /></label>
                    <label><span>主标题 <em>{(active.headline || "").length}/42</em></span><input value={active.headline || ""} maxLength={42}
                      onChange={(event) => patchImage(selected, { headline: event.target.value })}
                      onBlur={(event) => saveImageEdit(selected, { headline: event.target.value })} /></label>
                    <label><span>短标注（可选）</span><input value={active.callout || ""} maxLength={32}
                      onChange={(event) => patchImage(selected, { callout: event.target.value })}
                      onBlur={(event) => saveImageEdit(selected, { callout: event.target.value })} /></label>
                    <label><span>辅助说明 <em>{(active.supporting_text || "").length}/72</em></span><textarea value={active.supporting_text || ""} rows={2} maxLength={72}
                      onChange={(event) => patchImage(selected, { supporting_text: event.target.value })}
                      onBlur={(event) => saveImageEdit(selected, { supporting_text: event.target.value })} /></label>
                    <label><span>公开数据（仅短数字，如 8K/30fps）</span><input value={active.proof || ""} maxLength={20}
                      onChange={(event) => patchImage(selected, { proof: event.target.value })}
                      onBlur={(event) => saveImageEdit(selected, { proof: event.target.value })} /></label>
                    <div className="vs-form-row">
                      <label><span>版式</span><select value={active.layout_style || "editorial"}
                        onChange={(event) => saveImageEdit(selected, { layout_style: event.target.value })}>
                        {LAYOUTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                      <label><span>文字区</span><select value={active.text_zone || "top-left"}
                        onChange={(event) => saveImageEdit(selected, { text_zone: event.target.value, text_pos: event.target.value })}>
                        {ZONES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                    </div>
                  </div>
                )}

                <div className="vs-form-section">
                  <h4>成图验收</h4>
                  {active.final_url && (
                    <div className={`vs-render-qa ${active.render_qa?.ready ? "pass" : "fail"}`}>
                      <strong>{active.render_qa?.ready
                        ? active.render_qa.manual_visual_review_required ? "硬规则通过 · 待人工审美" : "成图质检通过"
                        : "成图质检未通过"}</strong>
                      <span>{active.render_qa?.score ?? 0} / 100</span>
                      {(active.render_qa?.issues || []).map((issue, index) => <p key={`${issue.code}-${index}`}>{issue.message}</p>)}
                    </div>
                  )}
                  <ul className="vs-criteria">
                    {(active.acceptance_criteria || []).map((item, index) => <li key={index}><Check size={12} />{item}</li>)}
                    <li><Check size={12} />产品、配件、Logo、接口和数量与实物一致</li>
                  </ul>
                  {active.final_url && (
                    <label className={`vs-review-check ${active.human_reviewed ? "checked" : ""}`}>
                      <input type="checkbox" checked={!!active.human_reviewed}
                        disabled={!active.render_qa?.ready}
                        onChange={(event) => saveImageEdit(selected, { human_reviewed: event.target.checked })} />
                      <ShieldCheck size={17} />
                      <span><strong>我已核对产品一致性</strong><small>{active.render_qa?.ready
                        ? "仅人工确认后，这张图才进入可交付状态"
                        : "必须先通过成图质检，当前不可勾选"}</small></span>
                    </label>
                  )}
                </div>

                {active.versions?.length > 0 && (
                  <div className="vs-form-section">
                    <h4>历史版本</h4>
                    <div className="vs-versions">
                      {active.versions.map((version, index) => (
                        <button key={`${version.url}-${index}`} onClick={() => restoreVersion(index)} title={`恢复版本 ${index + 1}`}>
                          <img src={version.url} alt="" /><span>v{index + 1}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <details className="vs-advanced">
                  <summary>高级设置 <ChevronDown size={13} /></summary>
                  <div>
                    <div className="vs-form-row">
                      <label><span>制作方式</span><input value="图片模型图文整图直出 · 高保真产品参考" disabled /></label>
                      <label><span>画布</span><input value={active.size || ""}
                        onChange={(event) => patchImage(selected, { size: event.target.value })}
                        onBlur={(event) => saveImageEdit(selected, { size: event.target.value })} /></label>
                    </div>
                    <label><span>最终图文生成指令</span><textarea value={active.render_prompt || ""} rows={10}
                      onChange={(event) => patchImage(selected, { render_prompt: event.target.value })}
                      onBlur={(event) => saveImageEdit(selected, { render_prompt: event.target.value })} /></label>
                  </div>
                </details>
              </aside>
            )}
          </div>
        </>
      )}

      {preview && (
        <div className="vs-lightbox" onClick={() => setPreview("")}>
          <img src={preview} alt="大图预览" onClick={(event) => event.stopPropagation()} />
        </div>
      )}
    </section>
  );
}
