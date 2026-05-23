import { useState } from "react";
import { autodetectSettings, patchSettings, getSettings } from "../../../api/settings";

type Props = {
  onDone: () => void;
};

const STEPS = ["welcome", "scan", "done"] as const;
type Step = (typeof STEPS)[number];

/**
 * First-run wizard shown when localStorage doesn't have the
 * "workspace-onboarded" flag. Three steps:
 *   1. Welcome card + summary of what Workspace does
 *   2. One-click autodetect — runs /api/settings/autodetect and offers to
 *      apply the suggestions (Hermes/Codex/Claude/Kiro/Bun paths). Skip
 *      button moves straight to "done".
 *   3. Done — short pointers (⌘K / "+ 新建" / 系统配置 →)
 *
 * Fully skippable; once dismissed the flag is set permanently. The
 * "重置 onboarding" link in /hub-settings can clear it later if needed.
 */
export default function Onboarding({ onDone }: Props) {
  const [step, setStep] = useState<Step>("welcome");
  const [scanning, setScanning] = useState(false);
  const [suggestions, setSuggestions] = useState<Record<string, string>>({});
  const [applied, setApplied] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const finish = () => {
    try { localStorage.setItem("opshub-workspace-onboarded", "1"); } catch { /* ignore */ }
    onDone();
  };

  const runScan = async () => {
    setScanning(true);
    setErr(null);
    try {
      const r = await autodetectSettings();
      setSuggestions(r.suggestions || {});
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "扫描失败");
    } finally {
      setScanning(false);
    }
  };

  const applyAll = async () => {
    try {
      // Only fill keys the user hasn't already set, so we don't overwrite
      // anything they configured before opening this wizard.
      const current = await getSettings();
      const patch: Record<string, string> = {};
      for (const [k, v] of Object.entries(suggestions)) {
        if (!v) continue;
        if (!(k in current.settings) || !(current.settings as any)[k]) {
          patch[k] = v;
        }
      }
      if (Object.keys(patch).length > 0) {
        await patchSettings(patch as any);
      }
      setApplied(true);
      // Auto-advance after a beat so the user sees the success state.
      setTimeout(() => setStep("done"), 700);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "应用失败");
    }
  };

  const entries = Object.entries(suggestions);

  return (
    <div className="onb-backdrop" onClick={(e) => { if (e.target === e.currentTarget) finish(); }}>
      <div className="onb-card">
        <button className="onb-skip" onClick={finish} title="跳过引导">跳过 ✕</button>

        {step === "welcome" && (
          <>
            <div className="onb-icon">◬</div>
            <h2 className="onb-title">欢迎使用工作台</h2>
            <p className="onb-text">
              这里聚合你在本机跑过的所有 AI 会话 ——
              <strong>ops-hub 自建</strong>、<strong>Claude Code</strong>、
              <strong>Codex</strong>，按工作目录自动分组成"项目"，每个项目下都
              能切 <strong>聊天 / 终端 / 文件 / Git</strong> tab。
            </p>
            <ul className="onb-list">
              <li><strong>⌘K / Ctrl+K</strong> 全局命令面板，跳转 / 搜索 / 触发动作</li>
              <li>外部历史会话可点「↻ 继续会话」拉起 CLI 续聊（自动 <code>--resume</code>）</li>
              <li>所有数据本地存储，没有云上传</li>
            </ul>
            <div className="onb-actions">
              <button className="tbtn" onClick={finish}>直接开始</button>
              <button className="tbtn tbtn-acc" onClick={() => setStep("scan")}>
                下一步：自动检测外部工具 →
              </button>
            </div>
          </>
        )}

        {step === "scan" && (
          <>
            <div className="onb-icon">⌕</div>
            <h2 className="onb-title">自动检测外部集成</h2>
            <p className="onb-text">
              扫描本机已安装的 <code>hermes</code> / <code>codex</code> / <code>claude</code> /
              <code>kiro-cli</code> 等工具，以及它们的 token 统计数据库
              （<code>~/.hermes/state.db</code> 等）。已经手动配置过的字段不会被覆盖。
            </p>
            {entries.length === 0 && !scanning && !err && (
              <div className="onb-scan-empty">
                <button className="tbtn tbtn-acc" onClick={runScan}>开始扫描</button>
              </div>
            )}
            {scanning && <div className="onb-scan-info">扫描中…</div>}
            {err && <div className="onb-err">⚠ {err}</div>}
            {entries.length > 0 && (
              <>
                <div className="onb-scan-list">
                  <div className="onb-scan-list-title">发现 {entries.length} 项可建议：</div>
                  {entries.map(([k, v]) => (
                    <div key={k} className="onb-scan-row">
                      <span className="onb-scan-key">{k}</span>
                      <span className="onb-scan-val" title={v}>{v}</span>
                    </div>
                  ))}
                </div>
                {applied ? (
                  <div className="onb-scan-applied">✓ 已应用</div>
                ) : (
                  <div className="onb-actions">
                    <button className="tbtn" onClick={() => setStep("done")}>跳过应用</button>
                    <button className="tbtn tbtn-acc" onClick={applyAll}>应用全部 →</button>
                  </div>
                )}
              </>
            )}
          </>
        )}

        {step === "done" && (
          <>
            <div className="onb-icon" style={{ color: "var(--acc)" }}>✓</div>
            <h2 className="onb-title">设置完成</h2>
            <p className="onb-text">
              你已经准备好用工作台了。几个关键操作快速回顾：
            </p>
            <ul className="onb-list">
              <li>按 <kbd>⌘K</kbd> / <kbd>Ctrl+K</kbd> 打开命令面板</li>
              <li>点顶部 <strong>+ 新建</strong> 在当前项目下开新会话</li>
              <li>顶部 <strong>⚙</strong> 看快捷设置；进一步配置去 <code>/hub-settings</code></li>
              <li>外部会话 → <strong>记录</strong> tab 看历史，<strong>↻ 继续会话</strong> 续聊</li>
            </ul>
            <div className="onb-actions">
              <button className="tbtn tbtn-acc" onClick={finish}>开始使用 →</button>
            </div>
          </>
        )}

        <div className="onb-progress">
          {STEPS.map((s) => (
            <span
              key={s}
              className={"onb-dot" + (s === step ? " active" : (STEPS.indexOf(s) < STEPS.indexOf(step) ? " done" : ""))}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
