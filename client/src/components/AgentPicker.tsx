import { useEffect, useMemo, useState } from "react";
import { AgentInfo, fetchAgents, rediscoverAgents } from "../api/agents";

type Props = {
  open: boolean;
  onClose: () => void;
  onConfirm: (params: { agent_id: string; model: string; title: string; workdir?: string }) => void;
};

// Modal that lets the user pick which agent to spawn for a new session.
//
// Step 1: pick an agent (cards show binary status & default model).
// Step 2: pick a model from that agent's catalog.
// Step 3: optionally tweak the title and the working directory.
//
// The whole flow lives in one modal — this is a personal hub, not a
// multi-step wizard.  ESC and backdrop click close.
export default function AgentPicker({ open, onClose, onConfirm }: Props) {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [model, setModel] = useState<string>("");
  const [title, setTitle] = useState<string>("");
  const [workdir, setWorkdir] = useState<string>("");

  const refresh = async (rediscover = false) => {
    setLoading(true);
    setError(null);
    try {
      const list = rediscover ? await rediscoverAgents() : await fetchAgents();
      setAgents(list);
      const firstEnabled = list.find((a) => a.enabled);
      if (firstEnabled) {
        setSelected(firstEnabled.id);
        setModel(firstEnabled.default_model || firstEnabled.models[0] || "");
      }
    } catch (e: any) {
      setError(e?.message || "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      refresh();
      setTitle("");
      setWorkdir("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const selectedAgent = useMemo(
    () => agents.find((a) => a.id === selected) || null,
    [agents, selected],
  );

  if (!open) return null;

  return (
    <div className="modal-bd" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="m-head">
          <span className="m-title">◆ 新建智能体会话</span>
          <button
            className="tbtn"
            onClick={() => refresh(true)}
            disabled={loading}
            title="重新探测已安装的 agent"
          >
            {loading ? <span className="spin" /> : "↻"} 重新探测
          </button>
          <button className="tbtn" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </div>

        <div className="m-body">
          {error && (
            <div className="inline-err" style={{ margin: "0 0 12px 0" }}>
              <span>⚠ {error}</span>
            </div>
          )}

          {/* Step 1: agent cards */}
          <div className="fg">
            <label>选择 Agent</label>
            <div className="ap-grid">
              {agents.map((a) => {
                const active = a.id === selected;
                return (
                  <button
                    key={a.id}
                    onClick={() => {
                      if (!a.enabled) return;
                      setSelected(a.id);
                      setModel(a.default_model || a.models[0] || "");
                    }}
                    disabled={!a.enabled}
                    className={"ap-card" + (active ? " active" : "")}
                  >
                    <div className="apc-name">{a.display_name}</div>
                    <div className="apc-meta">
                      {a.enabled ? (
                        <>
                          <span className="dot-on">●</span>
                          已安装
                        </>
                      ) : (
                        <>
                          <span className="dot-off">○</span>
                          未检测到
                        </>
                      )}
                    </div>
                    <div className="apc-meta">{a.models.length} 个模型</div>
                  </button>
                );
              })}
              {!agents.length && !loading && (
                <div style={{ color: "var(--t3)", fontSize: 11, gridColumn: "1 / -1", padding: 8 }}>
                  没有发现已安装的 agent
                </div>
              )}
              {loading && !agents.length && (
                <div style={{ color: "var(--t3)", fontSize: 11, gridColumn: "1 / -1", padding: 8, display: "flex", alignItems: "center", gap: 8 }}>
                  <span className="spin" /> 正在探测...
                </div>
              )}
            </div>
          </div>

          {/* Step 2: model + title + workdir */}
          {selectedAgent && (
            <>
              <div className="fg">
                <label>模型</label>
                <select
                  className="inp"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  style={{ paddingRight: 24 }}
                >
                  {selectedAgent.models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                  {!selectedAgent.models.includes(model) && model && (
                    <option value={model}>{model}（自定义）</option>
                  )}
                </select>
              </div>

              <div className="fg">
                <label>会话标题</label>
                <input
                  className="inp"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="例如：调试 listing.py"
                />
              </div>

              <div className="fg">
                <label>工作目录（可选，留空使用 home）</label>
                <input
                  className="inp"
                  value={workdir}
                  onChange={(e) => setWorkdir(e.target.value)}
                  placeholder="/path/to/your/project"
                />
              </div>
            </>
          )}
        </div>

        <div className="m-foot">
          <button className="tbtn" onClick={onClose}>
            取消
          </button>
          <button
            className="tbtn"
            style={{
              color: "var(--acc)",
              borderColor: "rgba(74,222,128,.4)",
              background: "rgba(74,222,128,.08)",
            }}
            onClick={() =>
              selectedAgent &&
              onConfirm({
                agent_id: selectedAgent.id,
                model: model || selectedAgent.default_model || "",
                title: title.trim() || `${selectedAgent.display_name} 会话`,
                workdir: workdir.trim() || undefined,
              })
            }
            disabled={!selectedAgent || !selectedAgent.enabled}
          >
            创建并打开
          </button>
        </div>
      </div>
    </div>
  );
}
