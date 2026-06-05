import { useCallback, useEffect, useState } from "react";
import { listMCPServers, addMCPServer, removeMCPServer, type MCPServer } from "../../../api/mcp";
import { useConfirm } from "../../../components/ConfirmDialog";
import SheetSelect from "../../../components/SheetSelect";

type Props = {
  open: boolean;
  onClose: () => void;
};

type Transport = "stdio" | "http";

/**
 * MCP server manager (Claude Code user-scope servers). Lists configured
 * servers and lets the user add a stdio (command) or http (url) server, or
 * remove one. Writes go through `claude mcp` server-side.
 */
export default function MCPManager({ open, onClose }: Props) {
  const confirm = useConfirm();
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Add form
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [transport, setTransport] = useState<Transport>("stdio");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [url, setUrl] = useState("");
  const [envText, setEnvText] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setServers(await listMCPServers());
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) refresh();
  }, [open, refresh]);

  const resetForm = () => {
    setName(""); setTransport("stdio"); setCommand(""); setArgs(""); setUrl(""); setEnvText("");
    setShowForm(false);
  };

  const parseEnv = (): Record<string, string> => {
    const env: Record<string, string> = {};
    for (const line of envText.split("\n")) {
      const t = line.trim();
      if (!t) continue;
      const i = t.indexOf("=");
      if (i > 0) env[t.slice(0, i).trim()] = t.slice(i + 1).trim();
    }
    return env;
  };

  const submit = async () => {
    if (!name.trim() || busy) return;
    let config: Record<string, unknown>;
    if (transport === "stdio") {
      if (!command.trim()) { setErr("请填写命令"); return; }
      config = { command: command.trim() };
      const a = args.trim().split(/\s+/).filter(Boolean);
      if (a.length) (config as any).args = a;
      const env = parseEnv();
      if (Object.keys(env).length) (config as any).env = env;
    } else {
      if (!url.trim()) { setErr("请填写 URL"); return; }
      config = { type: "http", url: url.trim() };
    }
    setBusy(true);
    setErr(null);
    try {
      await addMCPServer(name.trim(), config);
      resetForm();
      await refresh();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "添加失败");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (s: MCPServer) => {
    const ok = await confirm({ title: "删除 MCP 服务器", message: `确定删除「${s.name}」？`, confirmText: "删除", danger: true });
    if (!ok) return;
    setBusy(true);
    setErr(null);
    try {
      await removeMCPServer(s.name);
      await refresh();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "删除失败");
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <div className="mcp-backdrop" onClick={onClose}>
      <div className="mcp-modal" onClick={(e) => e.stopPropagation()}>
        <div className="mcp-head">
          <span className="mcp-title">⊞ MCP 服务器</span>
          <button className="tbtn" onClick={refresh} disabled={loading}>{loading ? "…" : "↻"}</button>
          <button className="tbtn" onClick={onClose} aria-label="关闭">✕</button>
        </div>

        {err && <div className="mcp-err">⚠ {err}</div>}

        <div className="mcp-body">
          {servers.length === 0 && !loading && (
            <div className="mcp-empty">还没有配置 MCP 服务器</div>
          )}
          {servers.map((s) => (
            <div key={s.name} className="mcp-row">
              <span className={"mcp-type mcp-type-" + s.type}>{s.type}</span>
              <div className="mcp-row-main">
                <div className="mcp-row-name">{s.name}</div>
                <div className="mcp-row-detail">
                  {s.type === "stdio"
                    ? [s.command, ...(s.args || [])].join(" ")
                    : s.url}
                  {s.env_keys.length > 0 && <span className="mcp-env"> · env: {s.env_keys.join(", ")}</span>}
                </div>
              </div>
              <button className="tbtn danger" onClick={() => remove(s)} disabled={busy} title="删除">🗑</button>
            </div>
          ))}
        </div>

        {showForm ? (
          <div className="mcp-form">
            <div className="mcp-form-row">
              <input className="inp" placeholder="服务器名（字母数字 _ . -）" value={name} onChange={(e) => setName(e.target.value)} />
              <SheetSelect className="inp" style={{ flex: "0 0 110px" }} value={transport} onChange={(v) => setTransport(v as Transport)}
                title="传输方式" options={[{ value: "stdio", label: "stdio" }, { value: "http", label: "http" }]} />
            </div>
            {transport === "stdio" ? (
              <>
                <input className="inp" placeholder="命令，如 npx" value={command} onChange={(e) => setCommand(e.target.value)} />
                <input className="inp" placeholder="参数（空格分隔），如 -y @modelcontextprotocol/server-filesystem /root" value={args} onChange={(e) => setArgs(e.target.value)} />
                <textarea className="inp" placeholder="环境变量（每行 KEY=VALUE，可留空）" value={envText} onChange={(e) => setEnvText(e.target.value)} rows={2} />
              </>
            ) : (
              <input className="inp" placeholder="URL，如 https://mcp.example.com/mcp" value={url} onChange={(e) => setUrl(e.target.value)} />
            )}
            <div className="mcp-form-actions">
              <button className="tbtn" onClick={resetForm} disabled={busy}>取消</button>
              <button className="tbtn tbtn-acc" onClick={submit} disabled={busy || !name.trim()}>{busy ? "添加中…" : "添加"}</button>
            </div>
          </div>
        ) : (
          <div className="mcp-foot">
            <button className="tbtn tbtn-acc" onClick={() => { setErr(null); setShowForm(true); }}>+ 添加服务器</button>
          </div>
        )}
      </div>
    </div>
  );
}
