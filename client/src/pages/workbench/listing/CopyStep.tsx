// 第二步：Listing 文案 —— 一键后台生成（四阶段进度），结果带字符数硬校验与逐条复制。
import { useState } from "react";
import { Copy, Loader2, RefreshCw, Sparkles } from "lucide-react";
import JobProgress from "./JobProgress";
import type { ListingState } from "./useListingProject";

const STAGES: [string, string][] = [
  ["vision", "图片识别"],
  ["competitor", "竞品数据"],
  ["generate", "文案生成"],
  ["done", "完成"],
];

function CharMeter({ value, limit }: { value: string; limit: number }) {
  const n = value.length;
  return <em className={`lst-charmeter${n > limit ? " over" : ""}`}>{n}/{limit}</em>;
}

function CopyBtn({ text, id, copied, onCopy }: { text: string; id: string; copied: string | null; onCopy: (text: string, id: string) => void }) {
  return (
    <button className="lst-copy-btn" onClick={() => onCopy(text, id)} title="复制">
      {copied === id ? "✓ 已复制" : <Copy size={10} />}
    </button>
  );
}

export default function CopyStep({ state }: { state: ListingState }) {
  const { project, productInfo, copyResult, jobs, runCopy } = state;
  const [copied, setCopied] = useState<string | null>(null);
  const [extraNotes, setExtraNotes] = useState("");

  const job = jobs.copy;
  const running = job?.status === "running";
  const res = copyResult;

  function copyText(text: string, id: string) {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(id);
      setTimeout(() => setCopied(null), 1500);
    });
  }

  const stageIndex = running ? Math.max(0, STAGES.findIndex(([key]) => key === job?.stage)) : -1;

  return (
    <div className="lst-step">
      <section className="card lst-section">
        <div className="lst-section-head">
          <div>
            <h3>Listing 文案</h3>
            <p>
              {project?.marketplace || "US"} · {project?.asin} · {productInfo.product_name || "（产品名未填写）"}
              　→　标题×5（≤75字符）· 亮点×1（≤125）· 五点×2套 · Search Terms×2
            </p>
          </div>
          <div className="lst-section-actions">
            <button className="lst-btn primary" onClick={() => void runCopy(extraNotes)} disabled={running}>
              {running ? <Loader2 size={12} className="spin" /> : res ? <RefreshCw size={12} /> : <Sparkles size={12} />}
              {running ? "生成中…" : res ? "重新生成" : "生成文案"}
            </button>
          </div>
        </div>

        <label className="lst-extra-notes">
          <span>补充要求（可选）</span>
          <input value={extraNotes} onChange={(e) => setExtraNotes(e.target.value)}
            placeholder="例如：突出防水性能；语气面向露营新手；避免提到电池容量" />
        </label>

        {running && (
          <div className="lst-copy-stages">
            {STAGES.map(([key, label], i) => {
              const done = i < stageIndex || job?.stage === "done";
              const active = i === stageIndex && job?.stage !== "done";
              return (
                <div key={key} className={`lst-copy-stage${done ? " done" : ""}${active ? " active" : ""}`}>
                  <i>{done ? "✓" : i + 1}</i>
                  <span>{label}</span>
                </div>
              );
            })}
          </div>
        )}
        <JobProgress job={job} onRetry={() => void runCopy(extraNotes)} />

        {!res && !running && (
          <div className="lst-empty-hint">
            点「生成文案」。服务端会自动带上产品信息、素材图视觉识别与本 ASIN 的竞品数据，全程后台运行，可离开页面。
          </div>
        )}
      </section>

      {res && !running && (
        <div className="lst-copy-results">
          {res.rationale && <div className="lst-callout info">{res.rationale}</div>}

          {(res.titles?.length ?? 0) > 0 && (
            <section className="card lst-copy-block">
              <header>
                <span>标题方案（{res.titles!.length} 个）</span>
                <CopyBtn text={res.titles!.join("\n\n")} id="titles" copied={copied} onCopy={copyText} />
              </header>
              {res.titles!.map((t, i) => (
                <div key={i} className="lst-copy-row">
                  <span className="lst-copy-index">T{i + 1}</span>
                  <span className="lst-copy-text">{t}</span>
                  <CharMeter value={t} limit={75} />
                  <CopyBtn text={t} id={`t${i}`} copied={copied} onCopy={copyText} />
                </div>
              ))}
            </section>
          )}

          {res.highlights && (
            <section className="card lst-copy-block">
              <header>
                <span>商品亮点 Highlights <CharMeter value={res.highlights} limit={125} /></span>
                <CopyBtn text={res.highlights} id="hl" copied={copied} onCopy={copyText} />
              </header>
              <div className="lst-copy-row"><span className="lst-copy-text">{res.highlights}</span></div>
            </section>
          )}

          {(["bullets_a", "bullets_b"] as const).map((key) => {
            const bullets = res[key];
            if (!bullets?.length) return null;
            const label = key === "bullets_a" ? "五点描述 Set A（转化焦点）" : "五点描述 Set B（Rufus 问答焦点）";
            return (
              <section key={key} className="card lst-copy-block">
                <header>
                  <span>{label}</span>
                  <CopyBtn text={bullets.join("\n\n")} id={key} copied={copied} onCopy={copyText} />
                </header>
                {bullets.map((b, i) => (
                  <div key={i} className="lst-copy-row">
                    <span className="lst-copy-index acc">{i + 1}.</span>
                    <span className="lst-copy-text">{b}</span>
                    <CopyBtn text={b} id={`${key}${i}`} copied={copied} onCopy={copyText} />
                  </div>
                ))}
              </section>
            );
          })}

          {(res.search_terms?.length ?? 0) > 0 && (
            <section className="card lst-copy-block">
              <header><span>后台 Search Terms</span></header>
              {res.search_terms!.map((st, i) => (
                <div key={i} className="lst-copy-row">
                  <span className="lst-copy-index">ST{i + 1}</span>
                  <span className="lst-copy-text breakall">{st}</span>
                  <CharMeter value={st} limit={249} />
                  <CopyBtn text={st} id={`st${i}`} copied={copied} onCopy={copyText} />
                </div>
              ))}
            </section>
          )}

          {(res.compliance_notes?.length ?? 0) > 0 && (
            <section className="lst-callout warn">
              <strong>合规检查</strong>
              {res.compliance_notes!.map((n, i) => <div key={i}>· {n}</div>)}
            </section>
          )}

          {!res.titles && res.raw && (
            <pre className="lst-analysis">{res.raw}</pre>
          )}
        </div>
      )}
    </div>
  );
}
