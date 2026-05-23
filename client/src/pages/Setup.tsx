/**
 * First-run Setup Wizard
 *
 * Shown once to new users who haven't set a password yet.
 * Four steps:
 *   0. Welcome
 *   1. Agent Detection + install
 *   2. API Keys (apimart + optional sorftime)
 *   3. Done
 *
 * On completion calls POST /api/setup/complete, then navigates to /.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { completeSetup, installAgentStreamUrl, type SetupChecks } from "../api/setup";
import { patchSettings } from "../api/settings";

// ---------------------------------------------------------------------------
// Tiny style helpers (inline, no extra CSS file needed)
// ---------------------------------------------------------------------------

const S = {
  page: {
    minHeight: "100vh",
    background: "var(--bg)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "24px 16px",
  } as React.CSSProperties,
  card: {
    width: "100%",
    maxWidth: 540,
    background: "var(--bg1)",
    border: "1px solid var(--b)",
    borderRadius: 8,
    padding: "32px 28px",
  } as React.CSSProperties,
  stepHeader: {
    fontSize: 9,
    letterSpacing: ".12em",
    color: "var(--t3)",
    textTransform: "uppercase" as const,
    marginBottom: 20,
  },
  title: { fontSize: 18, fontWeight: 600, color: "var(--t)", marginBottom: 6 },
  sub: { fontSize: 12, color: "var(--t2)", lineHeight: 1.6, marginBottom: 24 },
  label: { fontSize: 11, color: "var(--t2)", marginBottom: 5, display: "block" },
  input: {
    width: "100%",
    background: "var(--bg2)",
    border: "1px solid var(--b)",
    borderRadius: 4,
    padding: "7px 10px",
    color: "var(--t)",
    fontSize: 12,
    fontFamily: "var(--font)",
    boxSizing: "border-box" as const,
    outline: "none",
  } as React.CSSProperties,
  hint: { fontSize: 10, color: "var(--t3)", marginTop: 4, lineHeight: 1.5 },
  row: { display: "flex", gap: 10, marginTop: 20, justifyContent: "flex-end" },
  btnPrimary: {
    padding: "7px 20px",
    background: "var(--acc)",
    color: "#000",
    border: "none",
    borderRadius: 4,
    cursor: "pointer",
    fontSize: 12,
    fontFamily: "var(--font)",
    fontWeight: 600,
  } as React.CSSProperties,
  btnSecondary: {
    padding: "7px 16px",
    background: "transparent",
    color: "var(--t2)",
    border: "1px solid var(--b)",
    borderRadius: 4,
    cursor: "pointer",
    fontSize: 12,
    fontFamily: "var(--font)",
  } as React.CSSProperties,
  pill: (ok: boolean) => ({
    display: "inline-flex",
    alignItems: "center",
    gap: 5,
    padding: "3px 10px",
    borderRadius: 12,
    fontSize: 11,
    background: ok ? "rgba(74,222,128,.1)" : "rgba(248,113,113,.1)",
    color: ok ? "var(--acc)" : "var(--red)",
    border: `1px solid ${ok ? "rgba(74,222,128,.2)" : "rgba(248,113,113,.2)"}`,
  } as React.CSSProperties),
  logBox: {
    background: "var(--bg)",
    border: "1px solid var(--b)",
    borderRadius: 4,
    padding: "8px 10px",
    fontFamily: "monospace",
    fontSize: 11,
    color: "var(--t2)",
    maxHeight: 180,
    overflowY: "auto" as const,
    marginTop: 8,
    whiteSpace: "pre-wrap" as const,
    wordBreak: "break-all" as const,
  } as React.CSSProperties,
  stepDots: {
    display: "flex",
    gap: 6,
    marginBottom: 28,
    justifyContent: "center",
  } as React.CSSProperties,
};

function StepDots({ current, total }: { current: number; total: number }) {
  return (
    <div style={S.stepDots}>
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={i}
          style={{
            width: i === current ? 18 : 6,
            height: 6,
            borderRadius: 3,
            background: i === current ? "var(--acc)" : i < current ? "rgba(74,222,128,.35)" : "var(--b2)",
            transition: "all .2s",
          }}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Agent row component
// ---------------------------------------------------------------------------

type InstallState = "idle" | "installing" | "done" | "error";

function AgentRow({
  name,
  label,
  found,
  installHint,
}: {
  name: string;
  label: string;
  found: boolean;
  installHint?: string;
}) {
  const [state, setState] = useState<InstallState>(found ? "done" : "idle");
  const [log, setLog] = useState<string[]>([]);
  const logRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);

  const startInstall = () => {
    if (state === "installing") return;
    setState("installing");
    setLog([]);

    const es = new EventSource(installAgentStreamUrl(name));
    esRef.current = es;

    es.onmessage = (ev) => {
      const line = ev.data as string;
      if (line === "__DONE__") {
        setState("done");
        es.close();
      } else if (line === "__ERROR__") {
        setState("error");
        es.close();
      } else {
        setLog((prev) => [...prev, line]);
        setTimeout(() => {
          if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
        }, 0);
      }
    };
    es.onerror = () => {
      setState("error");
      setLog((prev) => [...prev, "Connection lost."]);
      es.close();
    };
  };

  const isOk = state === "done" || found;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "10px 12px",
        background: "var(--bg2)",
        border: "1px solid var(--b)",
        borderRadius: 6,
        marginBottom: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ flex: 1, fontSize: 12, color: "var(--t)" }}>{label}</span>
        <span style={S.pill(isOk)}>
          {isOk ? "✓ 已就绪" : state === "installing" ? "⏳ 安装中…" : state === "error" ? "✗ 失败" : "✗ 未安装"}
        </span>
        {!isOk && state !== "installing" && name !== "hermes" && (
          <button
            style={{ ...S.btnPrimary, padding: "4px 12px", fontSize: 11 }}
            onClick={startInstall}
          >
            安装
          </button>
        )}
        {!isOk && state === "error" && name !== "hermes" && (
          <button
            style={{ ...S.btnSecondary, padding: "4px 10px", fontSize: 11 }}
            onClick={startInstall}
          >
            重试
          </button>
        )}
      </div>

      {/* Hermes: can't auto-install, show link */}
      {!isOk && name === "hermes" && (
        <div style={S.hint}>
          Hermes 需要手动安装。请参考项目文档完成安装后，点「跳过」继续。
        </div>
      )}

      {installHint && !isOk && state === "idle" && name !== "hermes" && (
        <div style={S.hint}>{installHint}</div>
      )}

      {log.length > 0 && (
        <div ref={logRef} style={S.logBox}>
          {log.join("\n")}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 0 — Welcome
// ---------------------------------------------------------------------------

function StepWelcome({ onNext }: { onNext: () => void }) {
  return (
    <>
      <div style={S.title}>欢迎使用 ops-hub</div>
      <div style={S.sub}>
        ops-hub 是一个自托管的运营工作台，集成了 AI Agent、市场调研、广告审计、
        Listing 生成、知识库等功能。<br /><br />
        这个向导将帮你完成初始配置，只需 2 分钟。
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 8,
          marginBottom: 24,
        }}
      >
        {[
          ["🤖", "AI Agent", "hermes / codex / claude 本机运行"],
          ["🔍", "市场调研", "Sorftime 数据 + AI 分析"],
          ["🖼", "Listing 生成", "图片 + 文案一体化"],
          ["🧠", "知识库", "本地 GBrain + Markdown 笔记"],
        ].map(([icon, name, desc]) => (
          <div
            key={name}
            style={{
              padding: "10px 12px",
              background: "var(--bg2)",
              border: "1px solid var(--b)",
              borderRadius: 6,
            }}
          >
            <div style={{ fontSize: 16, marginBottom: 4 }}>{icon}</div>
            <div style={{ fontSize: 11, color: "var(--t)", fontWeight: 500 }}>{name}</div>
            <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 2 }}>{desc}</div>
          </div>
        ))}
      </div>
      <div style={S.row}>
        <button style={S.btnPrimary} onClick={onNext}>
          开始配置 →
        </button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Step 1 — Agent detection + install
// ---------------------------------------------------------------------------

function StepAgents({
  checks,
  onNext,
}: {
  checks: SetupChecks;
  onNext: () => void;
}) {
  const agents: Array<{ name: string; label: string; hint?: string }> = [
    {
      name: "hermes",
      label: "Hermes（推荐 · 自带 MCP + 飞书集成）",
    },
    {
      name: "codex",
      label: "Codex（OpenAI · npm install -g @openai/codex）",
      hint: "通过 npm 自动安装，需要本机有 Node.js 18+。",
    },
    {
      name: "claude",
      label: "Claude Code（Anthropic · npm install -g @anthropic-ai/claude-code）",
      hint: "通过 npm 自动安装，需要本机有 Node.js 18+。",
    },
  ];

  return (
    <>
      <div style={S.title}>AI Agent 检测</div>
      <div style={S.sub}>
        ops-hub 需要至少一个 Agent CLI 来驱动 AI 功能。检测到三个可选项，
        安装至少一个即可。已安装的会自动识别。
      </div>
      {agents.map((a) => (
        <AgentRow
          key={a.name}
          name={a.name}
          label={a.label}
          found={!!checks.agents[a.name]}
          installHint={a.hint}
        />
      ))}
      <div style={{ ...S.hint, marginTop: 4 }}>
        💡 三个都没安装也可以点「跳过」，后续在「系统配置」中安装完再使用 AI 功能。
      </div>
      <div style={S.row}>
        <button style={S.btnSecondary} onClick={onNext}>
          跳过
        </button>
        <button style={S.btnPrimary} onClick={onNext}>
          下一步 →
        </button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — API Keys
// ---------------------------------------------------------------------------

function StepApiKeys({
  checks,
  onNext,
}: {
  checks: SetupChecks;
  onNext: () => void;
}) {
  const [apimartKey, setApimartKey] = useState("");
  const [sortimeKey, setSortimeKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const save = async () => {
    setSaving(true);
    setErr("");
    try {
      const patch: Record<string, string> = {};
      if (apimartKey.trim()) patch.apimart_key = apimartKey.trim();
      if (sortimeKey.trim()) patch.sorftime_key = sortimeKey.trim();
      if (Object.keys(patch).length > 0) {
        await patchSettings(patch as any);
      }
      onNext();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div style={S.title}>基础密钥</div>
      <div style={S.sub}>
        填写你的 API 密钥。只有 Apimart 密钥是图片生成的必要条件，其他都可以后填。
      </div>

      <div style={{ marginBottom: 16 }}>
        <label style={S.label}>
          Apimart API 密钥{" "}
          <span
            style={{
              fontSize: 9,
              padding: "1px 5px",
              background: "rgba(74,222,128,.1)",
              color: "var(--acc)",
              borderRadius: 8,
              border: "1px solid rgba(74,222,128,.2)",
            }}
          >
            图片生成必填
          </span>
        </label>
        <input
          style={S.input}
          type="password"
          value={apimartKey}
          onChange={(e) => setApimartKey(e.target.value)}
          placeholder={checks.apimart_set ? "已配置（留空不修改）" : "sk-..."}
          autoComplete="off"
        />
        <div style={S.hint}>
          登录 apimart.ai → 控制台 → API Keys 获取。用于图片生成（gpt-image-2）。
        </div>
      </div>

      <div style={{ marginBottom: 16 }}>
        <label style={S.label}>
          Sorftime 市场数据密钥{" "}
          <span
            style={{
              fontSize: 9,
              padding: "1px 5px",
              background: "rgba(251,191,36,.1)",
              color: "var(--amber)",
              borderRadius: 8,
              border: "1px solid rgba(251,191,36,.2)",
            }}
          >
            可选
          </span>
        </label>
        <input
          style={S.input}
          type="password"
          value={sortimeKey}
          onChange={(e) => setSortimeKey(e.target.value)}
          placeholder="bho5v... （可后填）"
          autoComplete="off"
        />
        <div style={S.hint}>用于市场调研模块的销量、关键词、广告位数据。</div>
      </div>

      {err && (
        <div
          style={{
            fontSize: 11,
            color: "var(--red)",
            padding: "6px 10px",
            background: "rgba(248,113,113,.08)",
            border: "1px solid rgba(248,113,113,.2)",
            borderRadius: 4,
            marginBottom: 10,
          }}
        >
          {err}
        </div>
      )}

      <div style={S.row}>
        <button style={S.btnSecondary} onClick={onNext}>
          跳过
        </button>
        <button style={S.btnPrimary} onClick={save} disabled={saving}>
          {saving ? "保存中…" : "保存并继续 →"}
        </button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Step 3 — Done
// ---------------------------------------------------------------------------

function StepDone({ onFinish }: { onFinish: () => void }) {
  return (
    <>
      <div
        style={{
          textAlign: "center",
          padding: "20px 0",
        }}
      >
        <div style={{ fontSize: 40, marginBottom: 16 }}>✓</div>
        <div style={{ ...S.title, textAlign: "center" }}>配置完成</div>
        <div style={{ ...S.sub, textAlign: "center" }}>
          ops-hub 已就绪。随时可以在「系统配置」页修改或补充任何设置。
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr",
            gap: 8,
            margin: "20px 0",
          }}
        >
          {[
            ["工作台", "在 /agents 管理 Agent 会话"],
            ["系统配置", "随时补充密钥和集成路径"],
            ["市场调研", "开始你的第一次 ASIN 分析"],
          ].map(([name, desc]) => (
            <div
              key={name}
              style={{
                padding: "10px",
                background: "var(--bg2)",
                border: "1px solid var(--b)",
                borderRadius: 6,
                textAlign: "left",
              }}
            >
              <div style={{ fontSize: 11, color: "var(--acc)", marginBottom: 4 }}>{name}</div>
              <div style={{ fontSize: 10, color: "var(--t3)" }}>{desc}</div>
            </div>
          ))}
        </div>
        <button style={S.btnPrimary} onClick={onFinish}>
          进入工作台 →
        </button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main wizard
// ---------------------------------------------------------------------------

export default function Setup({ checks }: { checks: SetupChecks }) {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const TOTAL = 4;

  const next = () => setStep((s) => Math.min(s + 1, TOTAL - 1));

  const finish = async () => {
    try {
      await completeSetup();
    } catch {
      // best-effort; don't block navigation
    }
    navigate("/", { replace: true });
  };

  const STEP_LABELS = ["欢迎", "Agent", "密钥", "完成"];

  return (
    <div style={S.page}>
      <div style={S.card}>
        <div style={S.stepHeader}>
          设置向导 — {STEP_LABELS[step]} ({step + 1} / {TOTAL})
        </div>
        <StepDots current={step} total={TOTAL} />

        {step === 0 && <StepWelcome onNext={next} />}
        {step === 1 && <StepAgents checks={checks} onNext={next} />}
        {step === 2 && <StepApiKeys checks={checks} onNext={next} />}
        {step === 3 && <StepDone onFinish={finish} />}
      </div>
    </div>
  );
}
