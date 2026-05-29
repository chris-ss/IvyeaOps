import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  getSettings, patchSettings, getHealth, changePassword,
  testSetting, autodetectSettings,
  type HubSettings, type HealthResp, type TestResult,
} from "../../api/settings";

type SaveStatus = "idle" | "saving" | "ok" | "error";

// ── Tiny UI building blocks ───────────────────────────────────────────────────

function Dot({ ok, loading }: { ok?: boolean; loading?: boolean }) {
  if (loading) return <span className="hs-dot hs-dot-loading">…</span>;
  return <span className={"hs-dot " + (ok ? "hs-dot-ok" : "hs-dot-err")}>{ok ? "✓" : "✗"}</span>;
}

function Section({
  title, desc, children, keys, vals, onSave,
}: {
  title: React.ReactNode; desc?: React.ReactNode; children: React.ReactNode;
  keys: (keyof HubSettings)[]; vals: Partial<HubSettings>;
  onSave: (keys: (keyof HubSettings)[], vals: Partial<HubSettings>) => Promise<void>;
}) {
  const [status, setStatus] = useState<SaveStatus>("idle");
  const save = async () => {
    setStatus("saving");
    try { await onSave(keys, vals); setStatus("ok"); setTimeout(() => setStatus("idle"), 2200); }
    catch { setStatus("error"); setTimeout(() => setStatus("idle"), 3000); }
  };
  return (
    <div className="hs-section">
      <div className="hs-section-hd">
        <div>
          <div className="hs-section-title">{title}</div>
          {desc && <div className="hs-section-desc">{desc}</div>}
        </div>
        <button className={"hs-save-btn" + (status !== "idle" ? " hs-save-" + status : "")}
          onClick={save} disabled={status === "saving"}>
          {status === "saving" ? "保存中…" : status === "ok" ? "✓ 已保存" : status === "error" ? "× 失败" : "保存"}
        </button>
      </div>
      <div className="hs-fields">{children}</div>
    </div>
  );
}

function Field({ label, hint, children }: { label: React.ReactNode; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="hs-field">
      <label className="hs-label">{label}</label>
      {hint && <div className="hs-hint">{hint}</div>}
      {children}
    </div>
  );
}

function Tag({ kind, children }: { kind: "req" | "opt" | "rec"; children: React.ReactNode }) {
  return <span className={`hs-tag hs-tag-${kind}`}>{children}</span>;
}

function TestButton({ settingKey, value, label = "测试" }: {
  settingKey: keyof HubSettings;
  value: string | undefined;
  label?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const run = async () => {
    setBusy(true); setResult(null);
    try { setResult(await testSetting(settingKey, value)); }
    catch (e: any) { setResult({ ok: false, detail: e?.response?.data?.detail || e?.message || "请求失败" }); }
    finally { setBusy(false); setTimeout(() => setResult(null), 12000); }
  };
  return (
    <div className="hs-test-row">
      <button className="hs-test-btn" onClick={run} disabled={busy} type="button">
        {busy ? "测试中…" : `🔌 ${label}`}
      </button>
      {result && (
        <span className={"hs-test-result " + (result.ok ? "ok" : "err")}>
          {result.ok ? "✓" : "✗"} {result.detail}
        </span>
      )}
    </div>
  );
}

function AutodetectPanel({ onApply }: {
  onApply: (suggestions: Partial<Record<keyof HubSettings, string>>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<Partial<Record<keyof HubSettings, string>>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [err, setErr] = useState("");

  const scan = async () => {
    setLoading(true); setErr("");
    try {
      const r = await autodetectSettings();
      setSuggestions(r.suggestions);
      setSelected(new Set(Object.keys(r.suggestions)));
      setOpen(true);
    } catch (e: any) { setErr(e?.response?.data?.detail || e?.message || "检测失败"); }
    finally { setLoading(false); }
  };

  const apply = () => {
    const filtered: Partial<Record<keyof HubSettings, string>> = {};
    for (const k of Object.keys(suggestions)) {
      if (selected.has(k)) (filtered as any)[k] = (suggestions as any)[k];
    }
    onApply(filtered); setOpen(false);
  };

  const toggle = (k: string) => setSelected(prev => {
    const next = new Set(prev);
    if (next.has(k)) next.delete(k); else next.add(k);
    return next;
  });

  const entries = Object.entries(suggestions);

  return (
    <div className="hs-autodetect">
      <button className="hs-autodetect-btn" onClick={scan} disabled={loading} type="button">
        {loading ? "扫描中…" : "🔍 自动检测路径"}
      </button>
      {err && <div className="hs-autodetect-err">{err}</div>}
      {open && (
        <div className="hs-autodetect-modal-backdrop" onClick={() => setOpen(false)}>
          <div className="hs-autodetect-modal" onClick={(e) => e.stopPropagation()}>
            <div className="hs-autodetect-modal-hd">
              <div>
                <div className="hs-section-title">扫描到 {entries.length} 项</div>
                <div className="hs-section-desc">勾选项点「应用」后写入对应字段（只填当前为空的字段）。</div>
              </div>
              <button className="hs-test-btn" onClick={() => setOpen(false)} type="button">取消</button>
            </div>
            {entries.length === 0 ? (
              <div className="terminal-empty" style={{ padding: 20 }}>没有可建议的项。</div>
            ) : (
              <>
                <div className="hs-autodetect-list">
                  {entries.map(([k, v]) => (
                    <label key={k} className="hs-autodetect-item">
                      <input type="checkbox" checked={selected.has(k)} onChange={() => toggle(k)} />
                      <span className="hs-autodetect-key">{k}</span>
                      <span className="hs-autodetect-val">{v}</span>
                    </label>
                  ))}
                </div>
                <div className="hs-autodetect-modal-ft">
                  <button className="hs-test-btn" onClick={() => setSelected(new Set(entries.map(([k]) => k)))} type="button">全选</button>
                  <button className="hs-test-btn" onClick={() => setSelected(new Set())} type="button">清空</button>
                  <button className="hs-save-btn" onClick={apply} disabled={selected.size === 0} type="button" style={{ marginLeft: "auto" }}>
                    应用 {selected.size} 项 →
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function TxtInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return <input className="hs-input" type="text" value={value} onChange={e => onChange(e.target.value)}
    placeholder={placeholder} spellCheck={false} autoComplete="off" />;
}

function NumInput({ value, onChange, min, max, unit }: { value: number; onChange: (v: number) => void; min?: number; max?: number; unit?: string }) {
  return (
    <div className="hs-num-wrap">
      <input className="hs-input hs-input-num" type="number" value={value} min={min} max={max}
        onChange={e => onChange(Number(e.target.value))} />
      {unit && <span className="hs-unit">{unit}</span>}
    </div>
  );
}

function SecretInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [show, setShow] = useState(false);
  return (
    <div className="hs-secret-row">
      <input className="hs-input" type={show ? "text" : "password"} value={value}
        onChange={e => onChange(e.target.value)} placeholder={placeholder || "未配置"}
        spellCheck={false} autoComplete="new-password" />
      <button className="hs-eye" onClick={() => setShow(s => !s)} title={show ? "隐藏" : "显示"}>
        {show ? "●" : "○"}
      </button>
    </div>
  );
}

// ── Health panel (simplified) ─────────────────────────────────────────────────

function HealthPanel() {
  const [health, setHealth] = useState<HealthResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const check = useCallback(async () => {
    setLoading(true); setErr("");
    try { setHealth(await getHealth()); }
    catch (e: any) { setErr(e?.message || "检测失败"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { check(); }, [check]);

  const rows: Array<{ label: string; key: keyof HealthResp | string; nested?: string }> = [
    { label: "Apimart · 图片 / AI 服务", key: "apimart" },
    { label: "Sorftime · 市场数据",       key: "sorftime" },
    { label: "GBrain · 知识库 CLI",       key: "gbrain_bin" },
    { label: "Agent · hermes",            key: "runners", nested: "hermes" },
    { label: "Agent · codex",             key: "runners", nested: "codex" },
    { label: "Agent · claude",            key: "runners", nested: "claude" },
  ];

  const get = (row: typeof rows[0]) => {
    if (!health) return undefined;
    const top = health[row.key as keyof HealthResp] as any;
    if (row.nested) return top?.[row.nested];
    return top;
  };

  return (
    <div className="hs-health">
      <div className="hs-health-hd">
        <div>
          <div className="hs-section-title">系统状态</div>
          <div className="hs-section-desc" style={{ marginTop: 4 }}>
            <span style={{ color: "var(--acc)" }}>✓</span> 已就绪；
            <span style={{ color: "var(--red)", marginLeft: 6 }}>✗</span> 未配置或检测失败。
          </div>
        </div>
        <button className="hs-refresh-btn" onClick={check} disabled={loading}>
          {loading ? "检测中…" : "↻ 重新检测"}
        </button>
      </div>
      {err && <div className="hs-health-err">{err}</div>}
      <div className="hs-health-grid">
        {rows.map(row => {
          const item = get(row);
          return (
            <div key={row.label} className="hs-health-row">
              <Dot ok={item?.ok} loading={loading || (!health && !err)} />
              <span className="hs-health-label">{row.label}</span>
              <span className="hs-health-detail">{item?.detail || ""}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Change password ───────────────────────────────────────────────────────────

function ChangePassword() {
  const [old, setOld] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [msg, setMsg] = useState("");

  const save = async () => {
    if (next !== confirm) { setMsg("两次输入的新密码不一致"); return; }
    if (next.length < 8) { setMsg("新密码至少 8 位"); return; }
    setMsg(""); setStatus("saving");
    try {
      await changePassword(old, next);
      setStatus("ok"); setMsg("密码已更新");
      setOld(""); setNext(""); setConfirm("");
      setTimeout(() => { setStatus("idle"); setMsg(""); }, 3000);
    } catch (e: any) {
      setStatus("error"); setMsg(e?.response?.data?.detail || "修改失败");
      setTimeout(() => setStatus("idle"), 3000);
    }
  };

  return (
    <div className="hs-section">
      <div className="hs-section-hd">
        <div>
          <div className="hs-section-title">账号安全</div>
          <div className="hs-section-desc">
            修改登录密码（至少 8 位）。忘记密码时删掉 <code>data/hub_settings.json</code> 里的 <code>password_hash</code> 字段后重启服务。
          </div>
        </div>
        <button className={"hs-save-btn" + (status !== "idle" ? " hs-save-" + status : "")}
          onClick={save} disabled={status === "saving"}>
          {status === "saving" ? "保存中…" : status === "ok" ? "✓ 已更新" : status === "error" ? "× 失败" : "修改密码"}
        </button>
      </div>
      <div className="hs-fields">
        <div className="hs-row3">
          <Field label="当前密码">
            <SecretInput value={old} onChange={setOld} placeholder="当前密码" />
          </Field>
          <Field label="新密码">
            <SecretInput value={next} onChange={setNext} placeholder="至少 8 位" />
          </Field>
          <Field label="确认新密码">
            <SecretInput value={confirm} onChange={setConfirm} placeholder="再次输入" />
          </Field>
        </div>
        {msg && <div className={"hs-pw-msg" + (status === "ok" ? " ok" : " err")}>{msg}</div>}
      </div>
    </div>
  );
}

// ── Advanced accordion ────────────────────────────────────────────────────────

function AdvancedBlock({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="hs-advanced">
      <button
        type="button"
        className="hs-advanced-toggle"
        onClick={() => setOpen(o => !o)}
      >
        <span style={{ display: "inline-block", transition: "transform .15s", transform: open ? "rotate(90deg)" : "none" }}>▶</span>
        <span className="hs-advanced-toggle-label">高级选项</span>
        <span className="hs-advanced-toggle-sub">
          {open ? "点击收起" : "Token 监控 · Imgflow · 飞书通知 · CPU 告警 · 内嵌服务 · Kiro"}
        </span>
      </button>
      {open && <div className="hs-advanced-body">{children}</div>}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const EMPTY: HubSettings = {
  apimart_key: "", apimart_base: "https://api.apimart.ai/v1",
  text_ai_providers: "hermes,codex,claude",
  sorftime_key: "",
  imgflow_url: "http://127.0.0.1:3001",
  gbrain_bin: "", brain_root: "", openai_api_key: "",
  alert_webhook: "", alert_app_id: "", alert_app_secret: "", alert_chat_id: "",
  alert_threshold: 80, alert_sustain: 5, alert_cooldown: 30,
  dashboard_url: "", terminal_url: "",
  hermes_bin: "", codex_bin: "", claude_bin: "", kiro_cli_bin: "",
  hermes_db: "", codex_db: "", feishu_codex_db: "",
  kiro_gateway_db: "", kiro_cli_db: "", kiro_cli_sessions_dir: "",
  claude_projects_dir: "", hermes_node_bin: "", bun_bin: "",
  autofix_enabled: false,
};

export default function HubSettings() {
  const [vals, setVals] = useState<HubSettings>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");

  useEffect(() => {
    getSettings()
      .then(r => { setVals({ ...EMPTY, ...r.settings }); setLoading(false); })
      .catch(e => { setLoadErr(String(e?.response?.data?.detail || e?.message || "加载失败")); setLoading(false); });
  }, []);

  const set = useCallback(<K extends keyof HubSettings>(k: K, v: HubSettings[K]) => {
    setVals(prev => ({ ...prev, [k]: v }));
  }, []);

  const save = useCallback(async (keys: (keyof HubSettings)[], current: Partial<HubSettings>) => {
    const patch: Partial<HubSettings> = {};
    for (const k of keys) (patch as Record<string, unknown>)[k] = current[k];
    await patchSettings(patch);
  }, []);

  const applySuggestions = useCallback(async (sug: Partial<Record<keyof HubSettings, string>>) => {
    const patch: Partial<HubSettings> = {};
    for (const [k, v] of Object.entries(sug)) {
      if (v) (patch as Record<string, unknown>)[k] = v;
    }
    if (Object.keys(patch).length === 0) return;
    const r = await patchSettings(patch);
    setVals({ ...EMPTY, ...r.settings });
  }, []);

  // GBrain path fields collapsible
  const [gbrainPathsOpen, setGbrainPathsOpen] = useState(false);

  if (loading) return <div className="hs-loading">加载中…</div>;
  if (loadErr) return <div className="hs-error">加载失败：{loadErr}</div>;

  return (
    <div className="hs-page">

      {/* ── Header ── */}
      <div className="hs-header">
        <span className="hs-header-icon">⊙</span>
        <div>
          <div className="hs-header-title">系统配置</div>
          <div className="hs-header-sub">管理外部服务密钥与集成路径。每个区块独立保存。</div>
        </div>
      </div>

      <div className="hs-help">
        <Tag kind="req">必填</Tag> 缺失会导致对应功能不可用。
        <Tag kind="opt">可选</Tag> 留空也能正常运行。
        每个字段右侧 🔌 可在保存前验证当前值是否真的可用。
      </div>

      <AutodetectPanel onApply={applySuggestions} />
      <HealthPanel />

      {/* ── 1. 核心服务密钥 ── */}
      <Section
        title="核心服务密钥"
        desc="图片生成（Listing 模块）依赖 Apimart；市场调研依赖 Sorftime。这是大多数用户唯一需要填的两项。"
        keys={["apimart_key", "apimart_base", "sorftime_key"]}
        vals={vals} onSave={save}
      >
        <Field
          label={<><Tag kind="rec">推荐</Tag>Apimart API Key</>}
          hint={<>登录 apimart.ai → 控制台 → API Keys，复制 <code>sk-</code> 开头的密钥。用于图片生成；若密钥包含 Claude 文本权限也可用于文本 AI。</>}
        >
          <SecretInput value={vals.apimart_key} onChange={v => set("apimart_key", v)} placeholder="sk-..." />
          <TestButton settingKey="apimart_key" value={vals.apimart_key} label="测试密钥" />
        </Field>

        <Field
          label={<><Tag kind="opt">默认即可</Tag>Apimart API 地址</>}
          hint="除非使用自建网关或镜像站，否则保持默认值。"
        >
          <TxtInput value={vals.apimart_base} onChange={v => set("apimart_base", v)} placeholder="https://api.apimart.ai/v1" />
        </Field>

        <Field
          label={<><Tag kind="rec">推荐</Tag>Sorftime API Key</>}
          hint={<>登录 sorftime.com → 账户设置 → API → 复制密钥。市场调研模块必需，未订阅返回 401。</>}
        >
          <SecretInput value={vals.sorftime_key} onChange={v => set("sorftime_key", v)} placeholder="bho5v..." />
          <TestButton settingKey="sorftime_key" value={vals.sorftime_key} label="测试密钥" />
        </Field>
      </Section>

      {/* ── 2. AI 智能体 ── */}
      <Section
        title="AI 智能体"
        desc={<>hermes / codex / claude 三个本机 CLI 会从 PATH <strong>自动发现</strong>，通常不需要手动填路径。提供商顺序决定市场调研、广告审计等模块优先用哪个 AI。</>}
        keys={["text_ai_providers", "hermes_bin", "codex_bin", "claude_bin"]}
        vals={vals} onSave={save}
      >
        <Field
          label={<><Tag kind="opt">默认即可</Tag>提供商顺序</>}
          hint={<>逗号分隔，按顺序尝试。合法值：<code>hermes</code> <code>codex</code> <code>claude</code> <code>apimart</code>（后者需密钥有文本权限）。</>}
        >
          <TxtInput value={vals.text_ai_providers} onChange={v => set("text_ai_providers", v)} placeholder="hermes,codex,claude" />
        </Field>

        <Field
          label={<><Tag kind="opt">可选</Tag>hermes CLI 路径</>}
          hint="留空 = 从 PATH 自动发现。仅当自动发现失败时手动指定。"
        >
          <TxtInput value={vals.hermes_bin} onChange={v => set("hermes_bin", v)} placeholder="留空 = PATH 自动发现" />
          <TestButton settingKey="hermes_bin" value={vals.hermes_bin} label="测试路径" />
        </Field>

        <Field
          label={<><Tag kind="opt">可选</Tag>codex CLI 路径</>}
          hint={<>留空 = PATH 自动发现。安装：<code>npm install -g @openai/codex</code></>}
        >
          <TxtInput value={vals.codex_bin} onChange={v => set("codex_bin", v)} placeholder="留空 = PATH 自动发现" />
          <TestButton settingKey="codex_bin" value={vals.codex_bin} label="测试路径" />
        </Field>

        <Field
          label={<><Tag kind="opt">可选</Tag>claude CLI 路径</>}
          hint={<>留空 = PATH 自动发现。安装：<code>npm install -g @anthropic-ai/claude-code</code></>}
        >
          <TxtInput value={vals.claude_bin} onChange={v => set("claude_bin", v)} placeholder="留空 = PATH 自动发现" />
          <TestButton settingKey="claude_bin" value={vals.claude_bin} label="测试路径" />
        </Field>
      </Section>

      {/* ── 自动修复 Bug ── */}
      <Section
        title="自动修复 Bug"
        desc={<>开启后，任意功能在服务端报错（5xx）时会弹窗询问是否修复，AI（hermes）在<strong>隔离副本</strong>中排查并给出改动，由你审核 diff 后再应用并重启。默认关闭，仅管理员可见，关闭时零开销。</>}
        keys={["autofix_enabled"]}
        vals={vals} onSave={save}
      >
        <Field
          label={<><Tag kind="opt">默认关闭</Tag>启用自动修复</>}
          hint={<>仅在你信任 AI 改动当前生产代码时开启。修复全程审核制：应用前展示 diff；需重启时弹窗确认，<strong>60 秒</strong>无确认自动重启；改坏可一键回滚。</>}
        >
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--t2)", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={vals.autofix_enabled}
              onChange={e => set("autofix_enabled", e.target.checked)}
            />
            {vals.autofix_enabled ? "已开启（记得点右上角“保存”）" : "已关闭"}
          </label>
        </Field>
      </Section>

      {/* ── 3. GBrain 知识库 ── */}
      <Section
        title="GBrain 知识库"
        desc={<>安装 gbrain 后<strong>开箱即用</strong>（<code>bun install -g gbrain</code>）。笔记默认存 <code>~/brain</code>，无需任何配置。仅当你想换目录或自动发现失败时才需要展开下方选项。</>}
        keys={["brain_root", "gbrain_bin", "openai_api_key"]}
        vals={vals} onSave={save}
      >
        <button
          type="button"
          onClick={() => setGbrainPathsOpen(o => !o)}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            background: "transparent", border: "1px solid var(--b)", borderRadius: 4,
            padding: "5px 12px", color: "var(--t3)", fontSize: 11,
            cursor: "pointer", fontFamily: "var(--font)",
          }}
        >
          <span style={{ display: "inline-block", transition: "transform .15s", transform: gbrainPathsOpen ? "rotate(90deg)" : "none" }}>▶</span>
          自定义路径（通常无需展开）
        </button>

        {gbrainPathsOpen && (
          <div style={{ marginTop: 10, paddingLeft: 10, borderLeft: "2px solid var(--b)" }}>
            <Field
              label={<><Tag kind="opt">可选</Tag>知识库根目录</>}
              hint={<>Markdown 笔记存放目录。留空 = <code>~/brain</code>。</>}
            >
              <TxtInput value={vals.brain_root} onChange={v => set("brain_root", v)} placeholder="~/brain" />
              <TestButton settingKey="brain_root" value={vals.brain_root} label="测试路径" />
            </Field>

            <Field
              label={<><Tag kind="opt">可选</Tag>gbrain 可执行文件路径</>}
              hint={<>留空 = PATH 自动发现（通常在 <code>~/.bun/bin/gbrain</code>）。</>}
            >
              <TxtInput value={vals.gbrain_bin} onChange={v => set("gbrain_bin", v)} placeholder="留空 = PATH 自动发现" />
              <TestButton settingKey="gbrain_bin" value={vals.gbrain_bin} label="测试路径" />
            </Field>

            <Field
              label={<><Tag kind="opt">可选</Tag>OpenAI API Key</>}
              hint={<>仅语义检索（<code>gbrain embed</code>）需要，普通文本搜索无需填写。</>}
            >
              <SecretInput value={vals.openai_api_key} onChange={v => set("openai_api_key", v)} placeholder="sk-..." />
              <TestButton settingKey="openai_api_key" value={vals.openai_api_key} label="测试密钥" />
            </Field>
          </div>
        )}
      </Section>

      {/* ── 高级选项（折叠） ── */}
      <AdvancedBlock>

        {/* Token 用量监控 */}
        <Section
          title="Token 用量监控"
          desc="监控页扫描以下数据库统计 token 消耗。只读；留空或填错只会让对应数据源显示空白，不报错。路径均可自动发现，通常不需手动填。"
          keys={["hermes_db", "codex_db", "claude_projects_dir"]}
          vals={vals} onSave={save}
        >
          <Field label={<><Tag kind="opt">可选</Tag>Hermes state.db</>} hint={<>默认 <code>~/.hermes/state.db</code>，留空自动检测。</>}>
            <TxtInput value={vals.hermes_db} onChange={v => set("hermes_db", v)} placeholder="~/.hermes/state.db" />
            <TestButton settingKey="hermes_db" value={vals.hermes_db} label="测试 DB" />
          </Field>
          <Field label={<><Tag kind="opt">可选</Tag>Codex state DB</>} hint={<>默认 <code>~/.codex/state_5.sqlite</code>，留空自动检测。</>}>
            <TxtInput value={vals.codex_db} onChange={v => set("codex_db", v)} placeholder="~/.codex/state_5.sqlite" />
            <TestButton settingKey="codex_db" value={vals.codex_db} label="测试 DB" />
          </Field>
          <Field label={<><Tag kind="opt">可选</Tag>Claude projects 目录</>} hint={<>默认 <code>~/.claude/projects</code>，留空自动检测。</>}>
            <TxtInput value={vals.claude_projects_dir} onChange={v => set("claude_projects_dir", v)} placeholder="~/.claude/projects" />
            <TestButton settingKey="claude_projects_dir" value={vals.claude_projects_dir} label="测试目录" />
          </Field>
        </Section>

        {/* Listing Imgflow */}
        <Section
          title="Listing 生成（Imgflow）"
          desc={<>Listing Generator 的图片处理后端，需单独部署（<code>amazon-image-workflow</code> 项目）。不做 Listing 图片生成可忽略。</>}
          keys={["imgflow_url"]}
          vals={vals} onSave={save}
        >
          <Field label={<><Tag kind="opt">可选</Tag>imgflow 服务地址</>} hint={<>默认 <code>http://127.0.0.1:3001</code>，只填到端口，前端会自动追加 <code>/api</code>。</>}>
            <TxtInput value={vals.imgflow_url} onChange={v => set("imgflow_url", v)} placeholder="http://127.0.0.1:3001" />
            <TestButton settingKey="imgflow_url" value={vals.imgflow_url} label="测试连通性" />
          </Field>
        </Section>

        {/* 飞书通知 */}
        <Section
          title="飞书 / Lark 通知"
          desc="CPU 高位持续告警推送到飞书群。渠道 A（Webhook）和渠道 B（自建应用）任选其一，都不配置则不告警。"
          keys={["alert_webhook", "alert_app_id", "alert_app_secret", "alert_chat_id"]}
          vals={vals} onSave={save}
        >
          <Field label={<>Webhook 地址 <span style={{ color: "var(--t3)", marginLeft: 6 }}>渠道 A（推荐）</span></>}
            hint={<>群设置 → 群机器人 → 添加自定义机器人，复制 Webhook URL。需设关键词"ops-hub"或"CPU"。</>}>
            <SecretInput value={vals.alert_webhook} onChange={v => set("alert_webhook", v)}
              placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..." />
            <TestButton settingKey="alert_webhook" value={vals.alert_webhook} label="发测试消息" />
          </Field>
          <div className="hs-row3">
            <Field label={<>App ID <span style={{ color: "var(--t3)", marginLeft: 6 }}>渠道 B</span></>} hint="开放平台 → 凭证与基础信息，cli_ 开头。">
              <TxtInput value={vals.alert_app_id} onChange={v => set("alert_app_id", v)} placeholder="cli_xxx" />
            </Field>
            <Field label="App Secret">
              <SecretInput value={vals.alert_app_secret} onChange={v => set("alert_app_secret", v)} placeholder="App Secret" />
            </Field>
            <Field label="Chat ID" hint="目标群的 open_chat_id（oc_ 开头）。留空 = Hermes 默认频道。">
              <TxtInput value={vals.alert_chat_id} onChange={v => set("alert_chat_id", v)} placeholder="oc_..." />
            </Field>
          </div>
          <TestButton settingKey="alert_app_id" value={vals.alert_app_id} label="测试 App 凭证 + 发测试消息" />
        </Section>

        {/* CPU 告警阈值 */}
        <Section
          title="CPU 告警阈值"
          desc="cpu_alert.py 每分钟检查 ops-hub 进程 CPU，连续超阈值才告警。"
          keys={["alert_threshold", "alert_sustain", "alert_cooldown"]}
          vals={vals} onSave={save}
        >
          <div className="hs-row3">
            <Field label="触发阈值" hint="单核 100%；多核可超 100%。">
              <NumInput value={vals.alert_threshold} onChange={v => set("alert_threshold", v)} min={10} max={9999} unit="%" />
            </Field>
            <Field label="持续时长" hint="需连续高于阈值才告警，避免抖动误报。">
              <NumInput value={vals.alert_sustain} onChange={v => set("alert_sustain", v)} min={1} max={60} unit="分钟" />
            </Field>
            <Field label="冷却时间" hint="一次告警后等多久再发下一条。">
              <NumInput value={vals.alert_cooldown} onChange={v => set("alert_cooldown", v)} min={1} max={1440} unit="分钟" />
            </Field>
          </div>
        </Section>

        {/* 内嵌服务地址 */}
        <Section
          title="内嵌服务地址"
          desc="侧边栏「仪表盘」的 iframe 地址，以及终端页「新窗打开」的跳转 URL。留空则对应入口显示「未配置」。"
          keys={["dashboard_url", "terminal_url"]}
          vals={vals} onSave={save}
        >
          <Field label={<><Tag kind="opt">可选</Tag>仪表盘地址</>} hint="目标站点须允许 iframe 嵌入（X-Frame-Options）。">
            <TxtInput value={vals.dashboard_url} onChange={v => set("dashboard_url", v)} placeholder="https://hermes.example.com/" />
            <TestButton settingKey="dashboard_url" value={vals.dashboard_url} label="测试连通性" />
          </Field>
          <Field label={<><Tag kind="opt">可选</Tag>外部终端地址</>} hint="通常是独立部署的 ttyd Web 终端。">
            <TxtInput value={vals.terminal_url} onChange={v => set("terminal_url", v)} placeholder="https://term.example.com/" />
            <TestButton settingKey="terminal_url" value={vals.terminal_url} label="测试连通性" />
          </Field>
        </Section>

        {/* Kiro · 飞书-Codex · PATH */}
        <Section
          title="Kiro · 飞书-Codex 中继 · PATH 扩展"
          desc="未使用 Kiro 或 feishu-codex-relay 项目可完全忽略本区。PATH 扩展仅在子进程报「找不到 node/bun」时才需要填。"
          keys={["kiro_cli_bin", "kiro_gateway_db", "kiro_cli_db", "kiro_cli_sessions_dir", "feishu_codex_db", "hermes_node_bin", "bun_bin"]}
          vals={vals} onSave={save}
        >
          <div className="hs-field-group-title">Kiro CLI</div>
          <Field label={<><Tag kind="opt">可选</Tag>kiro-cli 路径</>} hint="留空 = PATH 自动发现。">
            <TxtInput value={vals.kiro_cli_bin as string} onChange={v => set("kiro_cli_bin", v)} placeholder="留空 = PATH 自动发现" />
            <TestButton settingKey="kiro_cli_bin" value={vals.kiro_cli_bin} label="测试路径" />
          </Field>
          <Field label={<><Tag kind="opt">可选</Tag>Kiro Gateway DB</>} hint={<>默认 <code>~/kiro-gateway/usage.db</code></>}>
            <TxtInput value={vals.kiro_gateway_db as string} onChange={v => set("kiro_gateway_db", v)} placeholder="~/kiro-gateway/usage.db" />
            <TestButton settingKey="kiro_gateway_db" value={vals.kiro_gateway_db} label="测试 DB" />
          </Field>
          <Field label={<><Tag kind="opt">可选</Tag>Kiro CLI 对话库</>} hint={<>默认 <code>~/.local/share/kiro-cli/data.sqlite3</code></>}>
            <TxtInput value={vals.kiro_cli_db as string} onChange={v => set("kiro_cli_db", v)} placeholder="~/.local/share/kiro-cli/data.sqlite3" />
            <TestButton settingKey="kiro_cli_db" value={vals.kiro_cli_db} label="测试 DB" />
          </Field>
          <Field label={<><Tag kind="opt">可选</Tag>Kiro CLI 会话目录</>} hint={<>默认 <code>~/.kiro/sessions/cli</code></>}>
            <TxtInput value={vals.kiro_cli_sessions_dir as string} onChange={v => set("kiro_cli_sessions_dir", v)} placeholder="~/.kiro/sessions/cli" />
            <TestButton settingKey="kiro_cli_sessions_dir" value={vals.kiro_cli_sessions_dir} label="测试目录" />
          </Field>

          <div className="hs-field-group-title" style={{ marginTop: 12 }}>飞书-Codex 中继</div>
          <Field label={<><Tag kind="opt">可选</Tag>飞书-Codex 中继 DB</>} hint={<>跑了 feishu-codex-relay 才需要填，默认 <code>~/feishu-codex-relay/.codex-home/state_5.sqlite</code></>}>
            <TxtInput value={vals.feishu_codex_db as string} onChange={v => set("feishu_codex_db", v)} placeholder="~/feishu-codex-relay/.codex-home/state_5.sqlite" />
            <TestButton settingKey="feishu_codex_db" value={vals.feishu_codex_db} label="测试 DB" />
          </Field>

          <div className="hs-field-group-title" style={{ marginTop: 12 }}>PATH 扩展</div>
          <Field label={<><Tag kind="opt">可选</Tag>Hermes 内置 Node 目录</>} hint={<>默认 <code>~/.hermes/node/bin</code>。子进程报 node not found 时填。</>}>
            <TxtInput value={vals.hermes_node_bin as string} onChange={v => set("hermes_node_bin", v)} placeholder="~/.hermes/node/bin" />
            <TestButton settingKey="hermes_node_bin" value={vals.hermes_node_bin} label="测试目录" />
          </Field>
          <Field label={<><Tag kind="opt">可选</Tag>Bun 运行时目录</>} hint={<>默认 <code>~/.bun/bin</code>。子进程报 bun not found 时填。</>}>
            <TxtInput value={vals.bun_bin as string} onChange={v => set("bun_bin", v)} placeholder="~/.bun/bin" />
            <TestButton settingKey="bun_bin" value={vals.bun_bin} label="测试目录" />
          </Field>
        </Section>

      </AdvancedBlock>

      {/* ── 账号安全 ── */}
      <ChangePassword />

      {/* ── Skill Studio ── */}
      <div className="hs-section hs-section-link">
        <div className="hs-section-hd">
          <div>
            <div className="hs-section-title">Skill Studio 配置</div>
            <div className="hs-section-desc">
              管理 Hermes / Claude Skill 文件的编辑器专属设置（快照保留、编辑器主题、Git 导入策略等）。
            </div>
          </div>
          <Link to="/skill/settings" className="hs-save-btn" style={{ textDecoration: "none" }}>
            前往配置 →
          </Link>
        </div>
      </div>

    </div>
  );
}
