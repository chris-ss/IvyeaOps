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

// Small status tags used in field labels: 必填 / 可选 / 推荐
function Tag({ kind, children }: { kind: "req" | "opt" | "rec"; children: React.ReactNode }) {
  return <span className={`hs-tag hs-tag-${kind}`}>{children}</span>;
}

// Inline "测试" button — calls /api/settings/test with the current (unsaved)
// value and shows the result next to the input. The test logic for each
// key lives in server/app/services/settings_test.py.
function TestButton({ settingKey, value, label = "测试" }: {
  settingKey: keyof HubSettings;
  value: string | undefined;
  label?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);

  const run = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await testSetting(settingKey, value);
      setResult(r);
    } catch (e: any) {
      setResult({ ok: false, detail: e?.response?.data?.detail || e?.message || "请求失败" });
    } finally {
      setBusy(false);
      // Auto-fade result after 12s
      setTimeout(() => setResult(null), 12000);
    }
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

// "自动检测" panel — scans the host for known integration paths and offers
// to fill empty fields in one click.
function AutodetectPanel({ onApply }: {
  onApply: (suggestions: Partial<Record<keyof HubSettings, string>>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<Partial<Record<keyof HubSettings, string>>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [err, setErr] = useState("");

  const scan = async () => {
    setLoading(true);
    setErr("");
    try {
      const r = await autodetectSettings();
      setSuggestions(r.suggestions);
      // Pre-select all suggestions by default — the user can untick what they don't want.
      setSelected(new Set(Object.keys(r.suggestions)));
      setOpen(true);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "检测失败");
    } finally {
      setLoading(false);
    }
  };

  const apply = () => {
    const filtered: Partial<Record<keyof HubSettings, string>> = {};
    for (const k of Object.keys(suggestions)) {
      if (selected.has(k)) {
        (filtered as any)[k] = (suggestions as any)[k];
      }
    }
    onApply(filtered);
    setOpen(false);
  };

  const toggle = (k: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k); else next.add(k);
      return next;
    });
  };

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
                <div className="hs-section-desc">已勾选项会在点「应用」时写入对应字段（不会覆盖你已经填过的值，所以只显示当前为空的）。</div>
              </div>
              <button className="hs-test-btn" onClick={() => setOpen(false)} type="button">取消</button>
            </div>
            {entries.length === 0 ? (
              <div className="terminal-empty" style={{ padding: 20 }}>
                没有可建议的项。要么你已经全配置好了，要么本机没装这些工具。
              </div>
            ) : (
              <>
                <div className="hs-autodetect-list">
                  {entries.map(([k, v]) => (
                    <label key={k} className="hs-autodetect-item">
                      <input
                        type="checkbox"
                        checked={selected.has(k)}
                        onChange={() => toggle(k)}
                      />
                      <span className="hs-autodetect-key">{k}</span>
                      <span className="hs-autodetect-val">{v}</span>
                    </label>
                  ))}
                </div>
                <div className="hs-autodetect-modal-ft">
                  <button className="hs-test-btn" onClick={() => setSelected(new Set(entries.map(([k]) => k)))} type="button">全选</button>
                  <button className="hs-test-btn" onClick={() => setSelected(new Set())} type="button">清空</button>
                  <button
                    className="hs-save-btn"
                    onClick={apply}
                    disabled={selected.size === 0}
                    type="button"
                    style={{ marginLeft: "auto" }}
                  >
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

// ── Health status panel ───────────────────────────────────────────────────────

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
    // 核心服务（影响主功能）
    { label: "Apimart · AI 服务",         key: "apimart" },
    { label: "Sorftime · 市场数据",       key: "sorftime" },
    { label: "Imgflow · Listing 生成",    key: "imgflow" },
    { label: "GBrain · 可执行文件",       key: "gbrain_bin" },
    { label: "GBrain · 知识库目录",       key: "brain_root" },
    { label: "OpenAI · 嵌入模型",         key: "openai" },
    // Agent 运行时（系统 PATH 探测，影响 Agent 选择器）
    { label: "Agent 运行时 · hermes",     key: "runners", nested: "hermes" },
    { label: "Agent 运行时 · codex",      key: "runners", nested: "codex" },
    { label: "Agent 运行时 · claude",     key: "runners", nested: "claude" },
    // 外部集成（仅影响监控页 token 统计 + Agent 高级用法，缺失不影响主功能）
    { label: "集成 · hermes CLI 路径",     key: "integrations", nested: "hermes_bin" },
    { label: "集成 · codex CLI 路径",      key: "integrations", nested: "codex_bin" },
    { label: "集成 · claude CLI 路径",     key: "integrations", nested: "claude_bin" },
    { label: "集成 · kiro-cli CLI 路径",   key: "integrations", nested: "kiro_cli_bin" },
    { label: "Token DB · Hermes",          key: "integrations", nested: "hermes_db" },
    { label: "Token DB · Codex",           key: "integrations", nested: "codex_db" },
    { label: "Token DB · 飞书-Codex 中继", key: "integrations", nested: "feishu_codex_db" },
    { label: "Token DB · Kiro Gateway",    key: "integrations", nested: "kiro_gateway_db" },
    { label: "Token DB · Kiro CLI 本地",   key: "integrations", nested: "kiro_cli_db" },
    { label: "Token 目录 · Kiro 会话",     key: "integrations", nested: "kiro_cli_sessions_dir" },
    { label: "Token 目录 · Claude 项目",   key: "integrations", nested: "claude_projects_dir" },
  ];

  const get = (row: typeof rows[0]): { ok: boolean; detail: string } | undefined => {
    if (!health) return undefined;
    const top = health[row.key as keyof HealthResp] as any;
    if (row.nested) return top?.[row.nested];
    return top;
  };

  return (
    <div className="hs-health">
      <div className="hs-health-hd">
        <div>
          <div className="hs-section-title">系统健康状态</div>
          <div className="hs-section-desc" style={{ marginTop: 4 }}>
            <span style={{ color: "var(--acc)" }}>✓</span> = 已配置且检测通过；
            <span style={{ color: "var(--red)", marginLeft: 6 }}>✗</span> = 未配置或检测失败。
            「集成」「Token DB / 目录」类是<strong>可选项</strong>，缺失不影响主功能，只是监控页相应数据源会显示空白。
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
            <div key={row.label + (row.nested || "")} className="hs-health-row">
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
            修改登录密码。新密码以 bcrypt 哈希存到 <code>data/hub_settings.json</code>，<strong>会覆盖 <code>.env</code> 里的 <code>OPSHUB_PASSWORD_HASH</code></strong>。<br />
            如果忘记密码：删掉 <code>data/hub_settings.json</code> 里的 <code>password_hash</code> 字段，或在服务器上跑 <code>cd server &amp;&amp; python -m app.core.hashpw</code> 重新生成 hash 写到 <code>.env</code>，然后重启服务。
          </div>
        </div>
        <button className={"hs-save-btn" + (status !== "idle" ? " hs-save-" + status : "")}
          onClick={save} disabled={status === "saving"}>
          {status === "saving" ? "保存中…" : status === "ok" ? "✓ 已更新" : status === "error" ? "× 失败" : "修改密码"}
        </button>
      </div>
      <div className="hs-fields">
        <div className="hs-row3">
          <Field label="当前密码" hint="用于身份验证，防止被人代改。">
            <SecretInput value={old} onChange={setOld} placeholder="当前密码" />
          </Field>
          <Field label="新密码" hint="至少 8 位，建议字母数字符号混搭。">
            <SecretInput value={next} onChange={setNext} placeholder="至少 8 位" />
          </Field>
          <Field label="确认新密码" hint="必须与新密码完全一致。">
            <SecretInput value={confirm} onChange={setConfirm} placeholder="再次输入" />
          </Field>
        </div>
        {msg && <div className={"hs-pw-msg" + (status === "ok" ? " ok" : " err")}>{msg}</div>}
      </div>
    </div>
  );
}

// ── Advanced integrations (Kiro + feishu-codex-relay + PATH augments) ────────
// Collapsed by default — most users will never need these.

function AdvancedIntegrations({
  vals,
  set,
}: {
  vals: Partial<HubSettings>;
  set: <K extends keyof HubSettings>(k: K, v: HubSettings[K]) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 12 }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          background: "transparent",
          border: "1px solid var(--b)",
          borderRadius: 4,
          padding: "5px 12px",
          color: "var(--t3)",
          fontSize: 11,
          cursor: "pointer",
          fontFamily: "var(--font)",
          width: "100%",
        }}
      >
        <span style={{ transition: "transform .15s", display: "inline-block", transform: open ? "rotate(90deg)" : "rotate(0)" }}>▶</span>
        高级选项（Kiro · 飞书-Codex 中继 · PATH 扩展）
        <span style={{ marginLeft: "auto", fontSize: 10 }}>
          {open ? "收起" : "如未使用 Kiro 可忽略"}
        </span>
      </button>
      {open && (
        <div style={{ marginTop: 10, paddingLeft: 10, borderLeft: "2px solid var(--b)" }}>
          <div className="hs-field-group-title">Kiro CLI</div>
          <Field label={<><Tag kind="opt">可选</Tag>kiro-cli</>}
            hint={<>Kiro CLI 绝对路径。装过 Kiro 的话 <code>which kiro-cli</code> 查路径。</>}>
            <TxtInput value={vals.kiro_cli_bin as string} onChange={v => set("kiro_cli_bin", v)} placeholder="留空 = PATH 自动发现" />
            <TestButton settingKey="kiro_cli_bin" value={vals.kiro_cli_bin} label="测试路径" />
          </Field>
          <Field label={<><Tag kind="opt">可选</Tag>Kiro Gateway DB</>}
            hint={<>Kiro Gateway（本地 AI API 代理）的用量库，默认 <code>~/kiro-gateway/usage.db</code>。</>}>
            <TxtInput value={vals.kiro_gateway_db as string} onChange={v => set("kiro_gateway_db", v)} placeholder="~/kiro-gateway/usage.db" />
            <TestButton settingKey="kiro_gateway_db" value={vals.kiro_gateway_db} label="测试 DB" />
          </Field>
          <Field label={<><Tag kind="opt">可选</Tag>Kiro CLI 对话库</>}
            hint={<>默认 <code>~/.local/share/kiro-cli/data.sqlite3</code>。</>}>
            <TxtInput value={vals.kiro_cli_db as string} onChange={v => set("kiro_cli_db", v)} placeholder="~/.local/share/kiro-cli/data.sqlite3" />
            <TestButton settingKey="kiro_cli_db" value={vals.kiro_cli_db} label="测试 DB" />
          </Field>
          <Field label={<><Tag kind="opt">可选</Tag>Kiro CLI 会话目录</>}
            hint={<>Kiro CLI 会话快照目录，默认 <code>~/.kiro/sessions/cli</code>。</>}>
            <TxtInput value={vals.kiro_cli_sessions_dir as string} onChange={v => set("kiro_cli_sessions_dir", v)} placeholder="~/.kiro/sessions/cli" />
            <TestButton settingKey="kiro_cli_sessions_dir" value={vals.kiro_cli_sessions_dir} label="测试目录" />
          </Field>

          <div className="hs-field-group-title" style={{ marginTop: 12 }}>飞书-Codex 中继</div>
          <Field label={<><Tag kind="opt">可选</Tag>飞书-Codex 中继 DB</>}
            hint={<>跑了 <code>feishu-codex-relay</code> 项目才需要填，默认 <code>~/feishu-codex-relay/.codex-home/state_5.sqlite</code>。</>}>
            <TxtInput value={vals.feishu_codex_db as string} onChange={v => set("feishu_codex_db", v)} placeholder="~/feishu-codex-relay/.codex-home/state_5.sqlite" />
            <TestButton settingKey="feishu_codex_db" value={vals.feishu_codex_db} label="测试 DB" />
          </Field>

          <div className="hs-field-group-title" style={{ marginTop: 12 }}>PATH 扩展（子进程找不到 node/bun 时填）</div>
          <Field label={<><Tag kind="opt">可选</Tag>Hermes 内置 Node 目录</>}
            hint={<>默认 <code>~/.hermes/node/bin</code>。Agent 子进程报 <code>node not found</code> 时填这里。</>}>
            <TxtInput value={vals.hermes_node_bin as string} onChange={v => set("hermes_node_bin", v)} placeholder="~/.hermes/node/bin" />
            <TestButton settingKey="hermes_node_bin" value={vals.hermes_node_bin} label="测试目录" />
          </Field>
          <Field label={<><Tag kind="opt">可选</Tag>Bun 运行时目录</>}
            hint={<>默认 <code>~/.bun/bin</code>。gbrain 子进程报 <code>bun not found</code> 时填这里。</>}>
            <TxtInput value={vals.bun_bin as string} onChange={v => set("bun_bin", v)} placeholder="~/.bun/bin" />
            <TestButton settingKey="bun_bin" value={vals.bun_bin} label="测试目录" />
          </Field>
        </div>
      )}
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

  // Apply autodetect suggestions: fill empty fields, persist immediately,
  // and refresh local state.
  const applySuggestions = useCallback(async (sug: Partial<Record<keyof HubSettings, string>>) => {
    const patch: Partial<HubSettings> = {};
    for (const [k, v] of Object.entries(sug)) {
      if (v) (patch as Record<string, unknown>)[k] = v;
    }
    if (Object.keys(patch).length === 0) return;
    const r = await patchSettings(patch);
    setVals({ ...EMPTY, ...r.settings });
  }, []);

  if (loading) return <div className="hs-loading">加载中…</div>;
  if (loadErr) return <div className="hs-error">加载失败：{loadErr}</div>;

  return (
    <div className="hs-page">
      <div className="hs-header">
        <span className="hs-header-icon">⊙</span>
        <div>
          <div className="hs-header-title">系统配置</div>
          <div className="hs-header-sub">集中管理所有外部服务的密钥、地址与可选集成。</div>
        </div>
      </div>

      <div className="hs-help">
        <strong>使用说明</strong>
        <ul style={{ margin: "6px 0 0", paddingLeft: 20 }}>
          <li>每个区块独立保存：点该区右上角「保存」只提交该区字段，互不影响。</li>
          <li>字段标签前的彩色 tag：<Tag kind="req">必填</Tag>没填会导致对应功能不可用；<Tag kind="rec">推荐</Tag>建议配置；<Tag kind="opt">可选</Tag>留空也行。</li>
          <li>留空字段会回退到 <code>server/.env</code> 里的 <code>OPSHUB_*</code> 变量，再没有就用内置默认。</li>
          <li>每个字段右下角的 <code>🔌 测试</code> 按钮可以验证当前输入是否真的可用（不用先保存）。顶部「自动检测路径」可一键发现本机已装的工具并填进空字段。</li>
          <li>密钥类改动即时生效；「内嵌服务地址」改完需要刷新对应页面；端口/Origin 等启动期配置改完需要重启服务。</li>
        </ul>
      </div>

      <AutodetectPanel onApply={applySuggestions} />

      <HealthPanel />

      {/* AI 服务 */}
      <Section
        title="AI 服务（Apimart）"
        desc={<>
          Apimart 是 OpenAI 兼容的统一代理网关。本站对 Apimart 有两类用途：<br />
          <strong>① 图片生成</strong>（<code>gpt-image-2</code>）— Listing Generator 模块用到，<strong>需要密钥</strong>。<br />
          <strong>② 文本生成</strong>（Claude 系列）— 可选，<strong>需要密钥包含 Claude 文本模型权限</strong>。
          市面常见 Apimart 套餐只买了图片权限，文本路径默认走本机 CLI（见下一区块）。
        </>}
        keys={["apimart_key", "apimart_base"]} vals={vals} onSave={save}>
        <Field
          label={<><Tag kind="rec">推荐</Tag>API 密钥</>}
          hint={<>登录 <a href="https://apimart.ai" target="_blank" rel="noreferrer">apimart.ai</a> → 控制台 → API Keys → 创建并复制完整字符串（<code>sk-</code> 开头）。仅图片用途时买 <code>gpt-image-2</code> 即可；要走 Claude 文本路径则另购 Claude 模型权限。</>}>
          <SecretInput value={vals.apimart_key} onChange={v => set("apimart_key", v)} placeholder="sk-..." />
          <TestButton settingKey="apimart_key" value={vals.apimart_key} label="测试密钥" />
        </Field>
        <Field
          label={<><Tag kind="opt">默认即可</Tag>API 地址</>}
          hint={<>Apimart 的 OpenAI 兼容端点。除非你换了自建网关、镜像站或代理，否则保持默认值 <code>https://api.apimart.ai/v1</code>。</>}>
          <TxtInput value={vals.apimart_base} onChange={v => set("apimart_base", v)} placeholder="https://api.apimart.ai/v1" />
          <TestButton settingKey="apimart_base" value={vals.apimart_base} label="测试连通性" />
        </Field>
      </Section>

      {/* 文本 AI 提供商顺序 */}
      <Section
        title="文本 AI 提供商顺序"
        desc={<>
          市场调研、广告审计、新闻摘要等模块需要文本大模型时，按此顺序依次尝试，第一个成功返回的提供商赢。
          默认 <code>hermes,codex,claude</code>（本机 CLI，免费、无网络依赖）。
          只有当你的 Apimart 密钥<strong>包含 Claude 文本权限</strong>时才把 <code>apimart</code> 加进列表（放最前可享流式 token，体验更顺滑）。
        </>}
        keys={["text_ai_providers"]} vals={vals} onSave={save}>
        <Field
          label={<><Tag kind="opt">默认即可</Tag>提供商顺序（逗号分隔）</>}
          hint={<>合法值：<code>hermes</code> / <code>codex</code> / <code>claude</code> / <code>apimart</code>。例：<code>apimart,hermes,codex,claude</code> 优先用 Apimart 流式，CLI 兜底。</>}>
          <TxtInput value={vals.text_ai_providers} onChange={v => set("text_ai_providers", v)} placeholder="hermes,codex,claude" />
        </Field>
      </Section>

      {/* 市场数据 */}
      <Section
        title="Sorftime 市场数据"
        desc={<>Sorftime 提供亚马逊产品销量、关键词、广告位、Review 等市场原始数据。市场调研模块、ASIN 审计的市场上下文都依赖这个数据源。不做市场分析可以留空。</>}
        keys={["sorftime_key"]} vals={vals} onSave={save}>
        <Field
          label={<><Tag kind="rec">推荐</Tag>API 密钥</>}
          hint={<>登录 <a href="https://sorftime.com" target="_blank" rel="noreferrer">sorftime.com</a> → 账户设置 → API → 复制 API Key。需要付费订阅才有 API 权限，未订阅会返回 401。</>}>
          <SecretInput value={vals.sorftime_key} onChange={v => set("sorftime_key", v)} placeholder="bho5v..." />
          <TestButton settingKey="sorftime_key" value={vals.sorftime_key} label="测试密钥" />
        </Field>
      </Section>

      {/* Listing 生成 */}
      <Section
        title="Listing 生成（Imgflow 后端）"
        desc={<>Listing Generator 模块（产品图片处理、PSD 解析、A+ 排版）依赖一个独立的 Node.js 后端服务 <code>imgflow</code>，需要单独部署（见 <code>amazon-image-workflow</code> 项目）。不做 Listing 图片生成可以忽略本区。</>}
        keys={["imgflow_url"]} vals={vals} onSave={save}>
        <Field
          label={<><Tag kind="opt">仅在用 Listing 模块时填</Tag>imgflow 服务地址</>}
          hint={<>imgflow 后端的根地址（含协议和端口）。默认 <code>http://127.0.0.1:3001</code> 表示同机部署。前端会自动追加 <code>/api</code> 路径，所以这里只填到端口即可。</>}>
          <TxtInput value={vals.imgflow_url} onChange={v => set("imgflow_url", v)} placeholder="http://127.0.0.1:3001" />
          <TestButton settingKey="imgflow_url" value={vals.imgflow_url} label="测试连通性" />
        </Field>
      </Section>

      {/* GBrain */}
      <Section
        title="GBrain 知识库"
        desc={<>GBrain 是一个本地的 Markdown 知识库 CLI（基于 Bun 运行时），把笔记按目录分类、按问题语义检索。Brain 对话模块、Agent 上下文增强会用它做 RAG 检索。不用知识库可以整个区留空。</>}
        keys={["gbrain_bin", "brain_root", "openai_api_key"]} vals={vals} onSave={save}>
        <Field
          label={<><Tag kind="opt">可选</Tag>GBrain 可执行文件路径</>}
          hint={<>gbrain 二进制的绝对路径。安装：<code>bun install -g gbrain</code>（通常装到 <code>~/.bun/bin/gbrain</code>）。留空时系统会按顺序找 <code>$PATH</code> → <code>/usr/local/bin/gbrain</code>。可用 <code>which gbrain</code> 查看你的实际路径。</>}>
          <TxtInput value={vals.gbrain_bin} onChange={v => set("gbrain_bin", v)} placeholder="/usr/local/bin/gbrain" />
          <TestButton settingKey="gbrain_bin" value={vals.gbrain_bin} label="测试路径" />
        </Field>
        <Field
          label={<><Tag kind="opt">可选</Tag>知识库根目录</>}
          hint={<>所有 <code>.md</code> 笔记按子目录分类存这里（<code>inbox/</code>、<code>amazon/</code>、<code>suppliers/</code> 等）。留空 = <code>~/brain</code>。目录不存在会自动创建。这是 gbrain 的工作目录，不是临时缓存。</>}>
          <TxtInput value={vals.brain_root} onChange={v => set("brain_root", v)} placeholder="~/brain" />
          <TestButton settingKey="brain_root" value={vals.brain_root} label="测试路径" />
        </Field>
        <Field
          label={<><Tag kind="opt">仅 embed 功能需要</Tag>OpenAI API Key</>}
          hint={<>仅当你启用 gbrain 的语义检索（<code>gbrain embed</code>）时才需要，用于调 OpenAI <code>text-embedding-3-*</code> 模型。从 <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">platform.openai.com</a> 获取，<code>sk-</code> 开头。仅文本搜索可以留空。</>}>
          <SecretInput value={vals.openai_api_key} onChange={v => set("openai_api_key", v)} placeholder="sk-..." />
          <TestButton settingKey="openai_api_key" value={vals.openai_api_key} label="测试密钥" />
        </Field>
      </Section>

      {/* 飞书通知 */}
      <Section
        title="飞书 / Lark 通知渠道"
        desc={<>当 ops-hub 自身 CPU 持续高位（默认 80% 持续 5 分钟）时，会推一条告警到飞书。下面两种渠道<strong>任选其一</strong>即可（都填会优先用 Webhook）。两种都不配置就不会有告警，但不影响 ops-hub 正常运行。</>}
        keys={["alert_webhook", "alert_app_id", "alert_app_secret", "alert_chat_id"]} vals={vals} onSave={save}>
        <div className="hs-help" style={{ borderLeftColor: "var(--acc)" }}>
          <strong>渠道 A · 自定义机器人 Webhook</strong>（推荐，5 分钟搞定）<br />
          飞书群里：<code>群设置 → 群机器人 → 添加机器人 → 自定义机器人</code>，复制生成的 Webhook URL 粘到下面。<br />
          ⚠ 飞书要求自定义机器人必须设<strong>关键词</strong>或<strong>签名校验</strong>之一才能收消息。设关键词时把"ops-hub"或"CPU"加进去，告警消息里已包含这些词。
        </div>
        <Field
          label={<>Webhook 地址 <span style={{ color: "var(--t3)", marginLeft: 6 }}>渠道 A</span></>}
          hint={<>形如 <code>https://open.feishu.cn/open-apis/bot/v2/hook/<i>xxx</i></code>。Lark 国际版域名是 <code>open.larksuite.com</code>。</>}>
          <SecretInput value={vals.alert_webhook} onChange={v => set("alert_webhook", v)}
            placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..." />
          <TestButton settingKey="alert_webhook" value={vals.alert_webhook} label="发测试消息" />
        </Field>
        <div className="hs-help" style={{ borderLeftColor: "var(--amber)" }}>
          <strong>渠道 B · 自建应用</strong>（适合已经有飞书 App 的人）<br />
          需要在飞书开放平台建一个企业自建应用，开通 <code>im:message:send_as_bot</code> 权限，把 bot 拉进目标群，然后填下面 3 个字段。<br />
          留空 Chat ID 时会自动使用 Hermes 的默认频道（<code>~/.hermes/.env</code> 里的 <code>FEISHU_HOME_CHANNEL</code>）。
        </div>
        <div className="hs-row3">
          <Field label={<>App ID <span style={{ color: "var(--t3)", marginLeft: 6 }}>渠道 B</span></>}
            hint={<>开放平台 → 应用详情 → 凭证与基础信息，<code>cli_</code> 开头。</>}>
            <TxtInput value={vals.alert_app_id} onChange={v => set("alert_app_id", v)} placeholder="cli_xxx" />
          </Field>
          <Field label="App Secret" hint={<>同上页面的 App Secret，不要外泄。</>}>
            <SecretInput value={vals.alert_app_secret} onChange={v => set("alert_app_secret", v)} placeholder="App Secret" />
          </Field>
          <Field label="Chat ID"
            hint={<>目标群的 <code>open_chat_id</code>（<code>oc_</code> 开头）。让 bot 进群后用飞书 API 或 hermes CLI 查询。留空 = Hermes 默认频道。</>}>
            <TxtInput value={vals.alert_chat_id} onChange={v => set("alert_chat_id", v)} placeholder="oc_..." />
          </Field>
        </div>
        <TestButton settingKey="alert_app_id" value={vals.alert_app_id} label="测试 App 凭证 + 发测试消息" />
      </Section>

      {/* 报警阈值 */}
      <Section
        title="CPU 报警阈值"
        desc={<>外置 cron 脚本 <code>scripts/cpu_alert.py</code> 每分钟检查一次 ops-hub 进程的 CPU 占用，连续超阈值才告警，避免抖动误报。这是为了防住"主程序卡死但 systemd 还以为活着"的兜底机制。</>}
        keys={["alert_threshold", "alert_sustain", "alert_cooldown"]} vals={vals} onSave={save}>
        <div className="hs-row3">
          <Field label="触发阈值"
            hint={<>进程 CPU 百分比。单核 100% = 占满一个核；<strong>多核机器可超 100%</strong>（每多吃一个核就多 100%）。默认 80% 适合 2-4 核机器，更多核可调高。</>}>
            <NumInput value={vals.alert_threshold} onChange={v => set("alert_threshold", v)} min={10} max={9999} unit="%" />
          </Field>
          <Field label="持续时长"
            hint={<>CPU 需要<strong>连续</strong>高于阈值多少分钟才告警。太短易误报，太长易错过短时卡死。建议 3–5 分钟。</>}>
            <NumInput value={vals.alert_sustain} onChange={v => set("alert_sustain", v)} min={1} max={60} unit="分钟" />
          </Field>
          <Field label="冷却时间"
            hint={<>一次告警后至少等多少分钟再发下一条。避免一次故障刷屏。建议 30–60 分钟。</>}>
            <NumInput value={vals.alert_cooldown} onChange={v => set("alert_cooldown", v)} min={1} max={1440} unit="分钟" />
          </Field>
        </div>
      </Section>

      {/* 内嵌服务地址 */}
      <Section
        title="内嵌服务地址"
        desc={<>侧边栏的「仪表盘」「AI 助手」入口会用 iframe 把下面的 URL 嵌进来；终端页的「新窗打开」按钮会跳到外部终端 URL。<strong>这些只是入口外链，留空对应入口会显示「未配置」提示，不影响主功能</strong>。改完需要<strong>刷新页面</strong>生效。</>}
        keys={["dashboard_url", "terminal_url"]} vals={vals} onSave={save}>
        <Field label={<><Tag kind="opt">可选</Tag>仪表盘地址</>}
          hint={<>侧边栏「仪表盘」页面 iframe 的目标 URL。通常指向你自己装的监控面板（Grafana / Hermes Dashboard / 自定义页面）。注意：目标站点必须允许被同域 iframe 嵌入（<code>X-Frame-Options</code> / <code>frame-ancestors</code> 配置）。</>}>
          <TxtInput value={vals.dashboard_url} onChange={v => set("dashboard_url", v)} placeholder="https://hermes.example.com/" />
          <TestButton settingKey="dashboard_url" value={vals.dashboard_url} label="测试连通性" />
        </Field>
        <Field label={<><Tag kind="opt">可选</Tag>外部终端地址</>}
          hint={<>主终端面板上「新窗打开」按钮的跳转地址，一般是独立部署的 <code>ttyd</code> Web 终端。内置的多终端工作台（终端列表那块）不受此影响。</>}>
          <TxtInput value={vals.terminal_url} onChange={v => set("terminal_url", v)} placeholder="https://term.example.com/" />
          <TestButton settingKey="terminal_url" value={vals.terminal_url} label="测试连通性" />
        </Field>
      </Section>

      {/* 外部集成路径 */}
      <Section
        title="Agent CLI 路径与 Token 统计"
        desc={<>ops-hub 会自动从 <code>$PATH</code> 发现已安装的 Agent CLI，这里可以手动指定绝对路径覆盖自动发现。<strong>留空时系统自动检测，通常不需要手动填。</strong></>}
        keys={[
          "hermes_bin", "codex_bin", "claude_bin", "kiro_cli_bin",
          "hermes_db", "codex_db", "feishu_codex_db",
          "kiro_gateway_db", "kiro_cli_db", "kiro_cli_sessions_dir",
          "claude_projects_dir", "hermes_node_bin", "bun_bin",
        ]} vals={vals} onSave={save}>

        <div className="hs-field-group-title">① Agent CLI 路径（留空 = PATH 自动发现）</div>
        <Field label={<><Tag kind="opt">可选</Tag>hermes CLI</>}
          hint={<>Hermes Agent CLI 绝对路径。常见位置 <code>~/.local/bin/hermes</code>。装好后 <code>which hermes</code> 即得。</>}>
          <TxtInput value={vals.hermes_bin} onChange={v => set("hermes_bin", v)} placeholder="留空 = PATH 自动发现" />
          <TestButton settingKey="hermes_bin" value={vals.hermes_bin} label="测试路径" />
        </Field>
        <Field label={<><Tag kind="opt">可选</Tag>codex CLI</>}
          hint={<>OpenAI Codex CLI 绝对路径。<code>npm install -g @openai/codex</code> 安装。</>}>
          <TxtInput value={vals.codex_bin} onChange={v => set("codex_bin", v)} placeholder="留空 = PATH 自动发现" />
          <TestButton settingKey="codex_bin" value={vals.codex_bin} label="测试路径" />
        </Field>
        <Field label={<><Tag kind="opt">可选</Tag>claude CLI</>}
          hint={<><code>npm install -g @anthropic-ai/claude-code</code> 安装。装好后 <code>readlink -f $(which claude)</code> 查看真实路径。</>}>
          <TxtInput value={vals.claude_bin} onChange={v => set("claude_bin", v)} placeholder="留空 = PATH 自动发现" />
          <TestButton settingKey="claude_bin" value={vals.claude_bin} label="测试路径" />
        </Field>

        <div className="hs-field-group-title">② Token 用量统计（监控页数据源）</div>
        <div className="hs-help">
          监控页会扫描以下数据库统计 token 消耗。<strong>只读，填错或留空只会让对应数据源空白，不报错。</strong>
        </div>
        <Field label={<><Tag kind="opt">可选</Tag>Hermes state.db</>}
          hint={<>默认 <code>~/.hermes/state.db</code>，留空自动检测。</>}>
          <TxtInput value={vals.hermes_db} onChange={v => set("hermes_db", v)} placeholder="~/.hermes/state.db" />
          <TestButton settingKey="hermes_db" value={vals.hermes_db} label="测试 DB" />
        </Field>
        <Field label={<><Tag kind="opt">可选</Tag>Codex state DB</>}
          hint={<>默认 <code>~/.codex/state_5.sqlite</code>，留空自动检测。</>}>
          <TxtInput value={vals.codex_db} onChange={v => set("codex_db", v)} placeholder="~/.codex/state_5.sqlite" />
          <TestButton settingKey="codex_db" value={vals.codex_db} label="测试 DB" />
        </Field>
        <Field label={<><Tag kind="opt">可选</Tag>Claude projects 目录</>}
          hint={<>Claude Code 会话日志目录，默认 <code>~/.claude/projects</code>。</>}>
          <TxtInput value={vals.claude_projects_dir} onChange={v => set("claude_projects_dir", v)} placeholder="~/.claude/projects" />
          <TestButton settingKey="claude_projects_dir" value={vals.claude_projects_dir} label="测试目录" />
        </Field>

        {/* Advanced: Kiro + feishu-codex-relay + PATH augments — collapsed by default */}
        <AdvancedIntegrations vals={vals} set={set} />
      </Section>

      {/* 账号安全 */}
      <ChangePassword />

      {/* Skill Studio 配置入口 */}
      <div className="hs-section hs-section-link">
        <div className="hs-section-hd">
          <div>
            <div className="hs-section-title">Skill Studio 配置</div>
            <div className="hs-section-desc">
              Skill Studio 是用来管理 Hermes / Claude Skill 文件（<code>SKILL.md</code> + 资源）的编辑器。它的专属设置（快照保留天数、回收站 TTL、CodeMirror 编辑器主题、Git 导入策略等）独立成一页，避免污染本页。
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
