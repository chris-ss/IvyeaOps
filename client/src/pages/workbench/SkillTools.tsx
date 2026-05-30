import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { listTools, runTool, pinTool, type SkillToolMeta, type SkillInput, type SseEvent } from "../../api/skillTools";
import { deleteSkill } from "../../api/skill";
import { useConfirm } from "../../components/ConfirmDialog";

export default function SkillTools() {
  const [tools, setTools] = useState<SkillToolMeta[]>([]);
  const [categories, setCategories] = useState<Record<string, number>>({});
  const [filterCat, setFilterCat] = useState<string>("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [activeTool, setActiveTool] = useState<SkillToolMeta | null>(null);
  const routerLoc = useLocation();
  const confirm = useConfirm();

  const handleDelete = useCallback(async (tool: SkillToolMeta, e?: React.MouseEvent) => {
    e?.stopPropagation();
    const ok = await confirm({
      title: "删除工具",
      message: `确定删除「${tool.description_zh || tool.name.split("/").pop()}」？\n该 Skill 会移入回收站，7 天内可在 Skill 管理中恢复。`,
      confirmText: "删除",
      danger: true,
    });
    if (!ok) return;
    try {
      // Unpin first so it leaves the sidebar, then trash the skill.
      if (tool.pinned) {
        try { await pinTool(tool.name, false); } catch { /* ignore */ }
      }
      await deleteSkill(tool.name);
      window.dispatchEvent(new CustomEvent("opshub:pinned-changed"));
      if (activeTool?.name === tool.name) setActiveTool(null);
      await loadTools();
    } catch { /* surfaced by reload */ }
  }, [confirm, activeTool]);

  const loadTools = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listTools(filterCat || undefined, search || undefined);
      setTools(res.tools);
      setCategories(res.categories);
      // Deep-link: ?tool=<name> opens that tool directly (sidebar pinned entry).
      const want = new URLSearchParams(window.location.search).get("tool");
      if (want && !activeTool) {
        const hit = res.tools.find((t) => t.name === want);
        if (hit) setActiveTool(hit);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, [filterCat, search]);

  useEffect(() => { loadTools(); }, [loadTools]);

  // React to sidebar deep-links: when ?tool= changes (or is cleared), open or
  // close the matching tool even if the page is already mounted.
  useEffect(() => {
    const want = new URLSearchParams(routerLoc.search).get("tool");
    if (!want) { setActiveTool(null); return; }
    setTools((cur) => {
      const hit = cur.find((t) => t.name === want);
      if (hit) setActiveTool(hit);
      return cur;
    });
  }, [routerLoc.search]);

  if (activeTool) {
    return (
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <button className="tbtn" onClick={() => setActiveTool(null)} style={{ fontSize: 11 }}>
            ← 返回运营商店
          </button>
          <button className="tbtn" onClick={() => handleDelete(activeTool)}
            style={{ fontSize: 11, marginLeft: "auto", color: "var(--red)", borderColor: "rgba(248,113,113,.35)" }}>
            🗑 删除工具
          </button>
        </div>
        <ToolPanel tool={activeTool} />
      </div>
    );
  }

  const catList = Object.entries(categories);

  return (
    <div>
      <div className="ptitle">/ 运营商店</div>
      <div style={{ fontSize: 10, color: "var(--t3)", marginBottom: 12 }}>
        从 Skill 自动生成的可视化操作工具，团队成员填参数即可执行
      </div>

      {/* Search + category filter */}
      <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
        <input
          className="market-query-input"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索工具…"
          style={{ flex: "1 1 200px" }}
        />
        <select
          className="market-query-input"
          style={{ flex: "0 0 140px" }}
          value={filterCat}
          onChange={(e) => setFilterCat(e.target.value)}
        >
          <option value="">全部分类 ({tools.length})</option>
          {catList.map(([cat, count]) => (
            <option key={cat} value={cat}>{cat} ({count})</option>
          ))}
        </select>
      </div>

      {loading && <div className="pulse-loading"><span className="pulse-spin">◌</span> 加载中…</div>}

      {!loading && tools.length === 0 && (
        <div className="market-empty">
          <div className="market-empty-icon">⊞</div>
          <div className="market-empty-title">暂无可执行工具</div>
          <div className="market-empty-hint">在「想法工坊」中创建 Skill 后，会自动出现在这里</div>
        </div>
      )}

      {/* Tool grid grouped by category */}
      {!loading && tools.length > 0 && (() => {
        const grouped: Record<string, SkillToolMeta[]> = {};
        for (const t of tools) {
          const cat = t.category || "(未分类)";
          if (!grouped[cat]) grouped[cat] = [];
          grouped[cat].push(t);
        }
        return Object.entries(grouped).map(([cat, items]) => (
          <div key={cat} style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "var(--t2)", marginBottom: 8, textTransform: "uppercase", letterSpacing: ".06em" }}>
              {cat}
            </div>
            <div className="g3">
              {items.map((t) => (
                <div
                  key={t.name}
                  className="card"
                  style={{ cursor: "pointer" }}
                  onClick={() => setActiveTool(t)}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <span style={{ fontSize: 18 }}>{t.icon}</span>
                    <span style={{ fontSize: 11, fontWeight: 600, color: "var(--t)" }}>
                      {t.name.split("/").pop()}
                    </span>
                    {t.inputs.length > 0 && (
                      <span className="tag" style={{ marginLeft: "auto", fontSize: 8 }}>
                        {t.inputs.length} 参数
                      </span>
                    )}
                    <button
                      onClick={(e) => handleDelete(t, e)}
                      title="删除工具（移入回收站）"
                      style={{ marginLeft: t.inputs.length > 0 ? 4 : "auto", background: "transparent", border: "none", color: "var(--t3)", cursor: "pointer", fontSize: 12, padding: "0 2px", lineHeight: 1 }}
                    >✕</button>
                  </div>
                  <div style={{ fontSize: 10, color: "var(--t3)", lineHeight: 1.5 }}>
                    {t.description_zh || t.description || "无描述"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ));
      })()}
    </div>
  );
}

/* ── Tool execution panel ── */

function ToolPanel({ tool }: { tool: SkillToolMeta }) {
  const [params, setParams] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const inp of tool.inputs) {
      init[inp.name] = inp.default || "";
    }
    return init;
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [output, setOutput] = useState("");
  const [provider, setProvider] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const setParam = (name: string, value: string) => {
    setParams((prev) => ({ ...prev, [name]: value }));
  };

  const run = useCallback(async () => {
    // Validate required
    for (const inp of tool.inputs) {
      if (inp.required && !params[inp.name]?.trim()) {
        setError(`请填写必填参数: ${inp.label}`);
        return;
      }
    }
    setLoading(true);
    setError("");
    setOutput("");
    setProvider("");
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await runTool(
        tool.name,
        params,
        (evt: SseEvent) => {
          if (evt.type === "token") {
            setOutput((prev) => prev + evt.text);
            setProvider(evt.provider);
          } else if (evt.type === "error") {
            setError(evt.detail);
          }
        },
        ctrl.signal,
      );
    } catch (e: any) {
      if (e.name !== "AbortError") setError(e?.message || "执行失败");
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  }, [tool, params, loading]);

  const [pinned, setPinned] = useState(!!tool.pinned);
  const [pinning, setPinning] = useState(false);
  const togglePin = useCallback(async () => {
    setPinning(true);
    try {
      const next = !pinned;
      await pinTool(tool.name, next);
      setPinned(next);
      // Notify the sidebar to refresh its pinned entries immediately.
      window.dispatchEvent(new CustomEvent("opshub:pinned-changed"));
    } catch { /* ignore */ } finally { setPinning(false); }
  }, [pinned, tool.name]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <div style={{ fontSize: 14, fontWeight: 600, flex: 1 }}>
          {tool.icon} {tool.name.split("/").pop()}
        </div>
        <button className="tbtn" onClick={togglePin} disabled={pinning}
          style={{ fontSize: 10, color: pinned ? "var(--acc)" : "var(--t3)", borderColor: pinned ? "var(--acc)" : "var(--b)" }}
          title={pinned ? "从侧边栏移除" : "固定到侧边栏作为独立工具"}>
          {pinned ? "★ 已固定侧边栏" : "☆ 固定到侧边栏"}
        </button>
      </div>
      <div style={{ fontSize: 10, color: "var(--t3)", marginBottom: 14 }}>
        {tool.description_zh || tool.description}
      </div>

      {/* Dynamic form */}
      {tool.inputs.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
          {tool.inputs.map((inp: SkillInput) => (
            <div key={inp.name}>
              <label style={{ fontSize: 10, color: "var(--t2)", display: "block", marginBottom: 3 }}>
                {inp.label}
                {inp.required && <span style={{ color: "#ef4444" }}>*</span>}
              </label>
              {inp.type === "select" && inp.options?.length > 0 ? (
                <select
                  className="market-query-input"
                  value={params[inp.name] || ""}
                  onChange={(e) => setParam(inp.name, e.target.value)}
                >
                  <option value="">{inp.placeholder || "请选择"}</option>
                  {inp.options.map((opt: string) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              ) : inp.type === "textarea" ? (
                <textarea
                  className="market-query-input"
                  value={params[inp.name] || ""}
                  onChange={(e) => setParam(inp.name, e.target.value)}
                  placeholder={inp.placeholder}
                  rows={3}
                  style={{ resize: "vertical", fontFamily: "inherit" }}
                />
              ) : (
                <input
                  className="market-query-input"
                  value={params[inp.name] || ""}
                  onChange={(e) => setParam(inp.name, e.target.value)}
                  placeholder={inp.placeholder}
                />
              )}
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: 10, color: "var(--t3)", marginBottom: 14 }}>
          此工具无可配置参数，点击直接执行。
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button className="market-btn market-btn-submit" onClick={run} disabled={loading}>
          {loading ? "执行中…" : "执行"}
        </button>
        {loading && (
          <button className="tbtn" onClick={() => abortRef.current?.abort()} style={{ fontSize: 10 }}>
            停止
          </button>
        )}
      </div>

      {error && <div className="market-error" style={{ marginTop: 10 }}>{error}</div>}

      {output && (
        <div style={{ marginTop: 14 }}>
          {provider && <div style={{ fontSize: 9, color: "var(--t3)", marginBottom: 4 }}>via {provider}</div>}
          <div
            className="card"
            style={{ background: "var(--bg2)", fontSize: 11, lineHeight: 1.7, whiteSpace: "pre-wrap" }}
            dangerouslySetInnerHTML={{ __html: simpleMarkdown(output) }}
          />
        </div>
      )}
    </div>
  );
}

function simpleMarkdown(md: string): string {
  return md
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/^### (.+)$/gm, '<div style="font-size:13px;font-weight:700;margin:10px 0 4px">$1</div>')
    .replace(/^## (.+)$/gm, '<div style="font-size:14px;font-weight:700;margin:12px 0 6px">$1</div>')
    .replace(/^# (.+)$/gm, '<div style="font-size:15px;font-weight:700;margin:14px 0 8px">$1</div>')
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, '<code style="background:var(--bg3);padding:1px 4px;border-radius:2px;font-size:10px">$1</code>')
    .replace(/\n/g, "<br>");
}
