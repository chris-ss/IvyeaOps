import { useCallback, useEffect, useMemo, useState } from "react";
import { useConfirm } from "../../components/ConfirmDialog";
import {
  brainChatCreate,
  brainChatGet,
  brainChatSend,
  brainChatSessions,
  brainChatStatus,
  brainChatUpdate,
  brainDoctor,
  brainFileRead,
  brainFileWrite,
  brainFileDelete,
  brainFiles,
  brainGetPage,
  brainImport,
  brainIngestText,
  brainIngestUrl,
  brainOverview,
  brainSearch,
  brainUpload,
  brainUploads,
  type BrainChatMessage,
  type BrainChatSession,
  type BrainChatStatus,
  type BrainFileItem,
  type BrainOverview,
  type BrainSearchItem,
  type BrainUploadItem,
  type BrainUploadResponse,
} from "../../api/client";

type Tab = "chat" | "upload" | "search" | "pages" | "templates" | "overview" | "settings";

const TABS: { key: Tab; label: string }[] = [
  { key: "chat", label: "对话" },
  { key: "upload", label: "上传" },
  { key: "search", label: "搜索" },
  { key: "pages", label: "页面" },
  { key: "templates", label: "亚马逊模板" },
  { key: "overview", label: "概览" },
  { key: "settings", label: "设置" },
];

const CATEGORIES = [
  ["inbox", "收件箱"],
  ["amazon", "Amazon"],
  ["products", "产品"],
  ["market", "市场"],
  ["ads", "广告"],
  ["compliance", "合规"],
  ["suppliers", "供应商"],
];

const TEMPLATES = [
  { key: "product", label: "产品页", path: "amazon/products/new-product.md", content: `# 产品页：待命名\n\n## 基础信息\n- ASIN：\n- 站点：US\n- 品牌：\n- 产品阶段：新品 / 盈利 / 重推 / 清货\n\n## 核心卖点\n- \n\n## 配置差异\n- 4G：\n- WiFi：\n- 电池/太阳能：\n\n## Listing 注意事项\n- 主图：\n- A+：\n- 合规风险：\n` },
  { key: "keyword", label: "关键词分析", path: "amazon/keywords/new-keyword.md", content: `# 关键词分析：待命名\n\n## 词根 / 精准词\n- 关键词：\n- 站点：US\n\n## 需求判断\n- 搜索量：\n- 季节性：\n- 进入时机：\n\n## 竞争判断\n- Top ASIN：\n- 集中度：\n- 差异化切口：\n\n## 广告动作\n- 精准：\n- 词组 / 广泛：\n- 否词：\n` },
  { key: "ad", label: "广告报告", path: "amazon/ads/new-ad-report.md", content: `# 广告报告：待命名\n\n## 背景\n- ASIN / SKU：\n- 目标：盈利 / 冲量 / 重推 / 清货\n- 时间范围：\n\n## 关键发现\n- CTR：\n- CVR：\n- ACOS：\n- 花费黑洞：\n\n## 动作清单\n1. \n2. \n3. \n` },
  { key: "message", label: "买家消息/合规", path: "amazon/messages/new-buyer-message.md", content: `# 买家消息模板：待命名\n\n## 场景\n- 售后问题：\n- 客户情绪：\n- 风险点：不索评、不站外引流、不用好评换补偿\n\n## 英文模板\nDear Customer,\n\n\nBest regards,\nCustomer Support\n\n## 德文模板\nGuten Tag,\n\n\nMit freundlichen Grüßen\nCustomer Support\n` },
  { key: "supplier", label: "供应商/1688 笔记", path: "amazon/suppliers/new-supplier-note.md", content: `# 供应商笔记：待命名\n\n## 产品\n- 名称：\n- 1688 链接：\n- 目标成本：\n\n## 规格\n- \n\n## 风险\n- 质量：\n- 认证：\n- 包装：\n- 交期：\n` },
];

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return <div className="met"><div className="ml">{label}</div><div className="mv" style={{ color: tone ?? "var(--t)" }}>{value}</div></div>;
}

function MiniAlert({ kind, children }: { kind: "ok" | "warn" | "bad" | "info"; children: React.ReactNode }) {
  const color = kind === "ok" ? "var(--acc)" : kind === "bad" ? "var(--red)" : kind === "warn" ? "var(--amber)" : "var(--blue)";
  return <div style={{ border: `1px solid ${color}55`, background: `${color}10`, color, padding: "8px 10px", borderRadius: 4, fontSize: 10, lineHeight: 1.6 }}>{children}</div>;
}

function ResultCard({ item, onOpen }: { item: BrainSearchItem; onOpen: (slug: string) => void }) {
  return (
    <div className="card" style={{ padding: "10px 12px", cursor: "pointer" }} onClick={() => onOpen(item.slug)}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span className="tag tg">{Number(item.score || 0).toFixed(3)}</span>
        <span style={{ color: "var(--t)", fontSize: 12 }}>{item.slug}</span>
      </div>
      <pre style={{ whiteSpace: "pre-wrap", color: "var(--t2)", fontSize: 10.5, lineHeight: 1.6, fontFamily: "var(--font)" }}>{item.snippet}</pre>
    </div>
  );
}

function safePathFromSlug(slug: string): string {
  const s = slug.replace(/^page:/, "").replace(/^\/+/, "");
  return s.endsWith(".md") ? s : `${s}.md`;
}

function getInitialTab(): Tab {
  const p = new URLSearchParams(window.location.search);
  const t = p.get("tab") as Tab | null;
  return TABS.some((x) => x.key === t) ? (t as Tab) : "chat";
}

export default function Brain() {
  const confirm = useConfirm();
  const [tab, setTabState] = useState<Tab>(getInitialTab);
  const [overview, setOverview] = useState<BrainOverview | null>(null);
  const [files, setFiles] = useState<BrainFileItem[]>([]);
  const [selectedPath, setSelectedPath] = useState<string>("");
  const [content, setContent] = useState("");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"search" | "query">("search");
  const [results, setResults] = useState<BrainSearchItem[]>([]);
  const [rawResult, setRawResult] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const [chatStatus, setChatStatus] = useState<BrainChatStatus | null>(null);
  const [sessions, setSessions] = useState<BrainChatSession[]>([]);
  const [activeSession, setActiveSession] = useState<BrainChatSession | null>(null);
  const [messages, setMessages] = useState<BrainChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [sending, setSending] = useState(false);

  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadCategory, setUploadCategory] = useState("inbox");
  const [uploadTitle, setUploadTitle] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [uploadMode, setUploadMode] = useState<"paste" | "file" | "url">("paste");
  const [urlInput, setUrlInput] = useState("");
  const [uploadResult, setUploadResult] = useState<BrainUploadResponse | null>(null);
  const [uploadHistory, setUploadHistory] = useState<BrainUploadItem[]>([]);

  const setTab = useCallback((next: Tab) => {
    setTabState(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    if (next !== "chat") url.searchParams.delete("session");
    window.history.replaceState({}, "", url.toString());
  }, []);

  const setActiveSessionUrl = useCallback((sessionId: string) => {
    localStorage.setItem("brain.lastSessionId", sessionId);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", "chat");
    url.searchParams.set("session", sessionId);
    window.history.replaceState({}, "", url.toString());
  }, []);

  const loadOverview = useCallback(async () => {
    setErr(null);
    try {
      const [o, status] = await Promise.all([brainOverview(), brainChatStatus()]);
      setOverview(o);
      setChatStatus(status);
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "概览加载失败");
    }
  }, []);

  const loadFiles = useCallback(async () => {
    try {
      const r = await brainFiles();
      setFiles(r.files);
      setSelectedPath((prev) => prev || r.files[0]?.path || "");
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "文件列表加载失败");
    }
  }, []);

  const loadUploads = useCallback(async () => {
    try {
      const r = await brainUploads();
      setUploadHistory(r.uploads);
    } catch {
      // non-critical
    }
  }, []);

  const loadSession = useCallback(async (sessionId: string) => {
    const r = await brainChatGet(sessionId);
    setActiveSession(r.session);
    setMessages(r.messages);
    setActiveSessionUrl(sessionId);
  }, [setActiveSessionUrl]);

  const loadChat = useCallback(async () => {
    try {
      const list = await brainChatSessions();
      setSessions(list.sessions);
      const params = new URLSearchParams(window.location.search);
      const target = params.get("session") || localStorage.getItem("brain.lastSessionId") || list.sessions[0]?.id;
      if (target && list.sessions.some((s) => s.id === target)) {
        await loadSession(target);
      } else if (list.sessions[0]) {
        await loadSession(list.sessions[0].id);
      } else {
        const created = await brainChatCreate("新知识对话", "amazon_operator");
        setSessions([created.session]);
        setActiveSession(created.session);
        setMessages(created.messages);
        setActiveSessionUrl(created.session.id);
      }
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "会话加载失败");
    }
  }, [loadSession, setActiveSessionUrl]);

  useEffect(() => {
    loadOverview();
    loadFiles();
    loadUploads();
    loadChat();
  }, [loadOverview, loadFiles, loadUploads, loadChat]);

  const selectedFile = useMemo(() => files.find((f) => f.path === selectedPath), [files, selectedPath]);
  const stats = overview?.stats;
  const embedOn = overview && (overview.embed_configured ?? overview.openai_configured);
  const noEmbed = overview && !embedOn;

  const openFile = useCallback(async (path: string) => {
    if (!path) return;
    setLoading(true);
    setErr(null);
    try {
      const r = await brainFileRead(path);
      setSelectedPath(r.path);
      setContent(r.content);
      setTab("pages");
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "读取失败");
    } finally {
      setLoading(false);
    }
  }, [setTab]);

  useEffect(() => {
    if (tab === "pages" && selectedPath && !content) openFile(selectedPath);
  }, [tab, selectedPath, content, openFile]);

  const doSearch = async () => {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setErr(null);
    try {
      const r = await brainSearch(q, mode);
      setResults(r.items);
      setRawResult(r.raw);
      if (r.items.length === 0 && r.raw) setFlash("没有解析到标准结果，已显示原始输出。");
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "搜索失败");
    } finally {
      setLoading(false);
    }
  };

  const openSlug = async (slug: string) => {
    const path = safePathFromSlug(slug);
    setLoading(true);
    setErr(null);
    try {
      const r = await brainGetPage(slug);
      setSelectedPath(path);
      setContent(r.content);
      setTab("pages");
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "页面打开失败");
    } finally {
      setLoading(false);
    }
  };

  const save = async (importAfter = false) => {
    if (!selectedPath.trim()) {
      setErr("请先选择或输入 .md 路径");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const r = await brainFileWrite(selectedPath.trim(), content);
      setSelectedPath(r.path);
      if (importAfter) {
        const imp = await brainImport();
        setFlash(`已保存并导入：${imp.raw || "OK"}`);
        await loadOverview();
      } else {
        setFlash('已保存到知识库目录；如需进入 GBrain 索引，请点击「保存并导入」。');
      }
      await loadFiles();
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const createTemplate = async (tpl: (typeof TEMPLATES)[number]) => {
    setSelectedPath(tpl.path);
    setContent(tpl.content);
    setTab("pages");
    setFlash(`已载入模板：${tpl.label}。检查路径后保存。`);
  };

  const runDoctor = async () => {
    setLoading(true);
    setErr(null);
    try {
      const d = await brainDoctor();
      setFlash(JSON.stringify(d, null, 2));
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "Doctor 失败");
    } finally {
      setLoading(false);
    }
  };

  const newChat = async () => {
    setSending(true);
    setErr(null);
    try {
      const r = await brainChatCreate("新知识对话", "amazon_operator");
      setSessions((prev) => [r.session, ...prev]);
      setActiveSession(r.session);
      setMessages(r.messages);
      setTab("chat");
      setActiveSessionUrl(r.session.id);
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "新建会话失败");
    } finally {
      setSending(false);
    }
  };

  const archiveChat = async (sessionId: string) => {
    try {
      await brainChatUpdate(sessionId, { archived: true });
      await loadChat();
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "归档失败");
    }
  };

  const sendChat = async () => {
    const text = chatInput.trim();
    if (!text || !activeSession) return;
    setSending(true);
    setErr(null);
    setChatInput("");
    const optimistic: BrainChatMessage = { id: `local-${Date.now()}`, session_id: activeSession.id, role: "user", content: text, citations: [], created_at: new Date().toISOString() };
    setMessages((prev) => [...prev, optimistic]);
    try {
      const r = await brainChatSend(activeSession.id, text);
      setMessages((prev) => [...prev.filter((m) => m.id !== optimistic.id), r.user_message, r.assistant_message]);
      const list = await brainChatSessions();
      setSessions(list.sessions);
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "发送失败");
      setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
      setChatInput(text);
    } finally {
      setSending(false);
    }
  };

  const doUpload = async () => {
    if (!uploadFile) {
      setErr("请先选择文件");
      return;
    }
    setSaving(true);
    setErr(null);
    setUploadResult(null);
    try {
      const r = await brainUpload(uploadFile, uploadCategory, uploadTitle || uploadFile.name, true);
      setUploadResult(r);
      setFlash(`已保存知识：${r.saved_path}`);
      await Promise.all([loadFiles(), loadOverview(), loadUploads()]);
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "上传失败");
    } finally {
      setSaving(false);
    }
  };

  const doIngestText = async () => {
    const text = pasteText.trim();
    if (!text) {
      setErr("请先粘贴要入库的文本内容");
      return;
    }
    setSaving(true);
    setErr(null);
    setUploadResult(null);
    try {
      const r = await brainIngestText(text, true);
      setUploadResult(r);
      setFlash(`已自动分析并保存知识：${r.saved_path}`);
      setPasteText("");
      await Promise.all([loadFiles(), loadOverview(), loadUploads()]);
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "粘贴入库失败");
    } finally {
      setSaving(false);
    }
  };

  const doIngestUrl = async () => {
    const url = urlInput.trim();
    if (!url) return;
    setSaving(true);
    setErr(null);
    setUploadResult(null);
    try {
      const r = await brainIngestUrl(url, true);
      setUploadResult(r);
      setFlash(`已抓取并保存：${r.saved_path}`);
      setUrlInput("");
      await Promise.all([loadFiles(), loadOverview(), loadUploads()]);
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "URL抓取失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="ptitle">/ GBrain 知识库</div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
        <span className="tag tg">LOCAL BRAIN</span>
        <span style={{ color: "var(--t2)", fontSize: 11 }}>上传 / 对话 / 编辑本地知识库：先检索 GBrain，再调用本机 Hermes 对话；不新增公网端口</span>
        <button className="tbtn" onClick={() => { loadOverview(); loadFiles(); loadUploads(); loadChat(); }} style={{ marginLeft: "auto" }}>刷新</button>
      </div>

      {err && <div style={{ marginBottom: 10 }}><MiniAlert kind="bad">{err}</MiniAlert></div>}
      {flash && <div style={{ marginBottom: 10 }}><MiniAlert kind="info"><pre style={{ whiteSpace: "pre-wrap", fontFamily: "var(--font)" }}>{flash}</pre></MiniAlert></div>}
      {noEmbed && <div style={{ marginBottom: 10 }}><MiniAlert kind="warn">未配置 Embedding：当前以关键词检索为主（功能正常）。如需语义检索，前往 系统配置 → 智能体 → 知识库语义检索 选择服务商（Ollama 本地免费）。</MiniAlert></div>}
      {chatStatus && !chatStatus.configured && tab === "chat" && <div style={{ marginBottom: 10 }}><MiniAlert kind="warn">Hermes 对话不可用：没有找到 hermes CLI。上传、搜索、页面编辑仍可用。</MiniAlert></div>}

      <div className="tabs" style={{ overflowX: "auto" }}>
        {TABS.map((t) => <button key={t.key} className={"tab" + (tab === t.key ? " active" : "")} onClick={() => setTab(t.key)}>{t.label}</button>)}
      </div>

      {tab === "chat" && (
        <div style={{ display: "grid", gridTemplateColumns: "160px minmax(0, 1fr)", gap: 10 }} className="brain-chat-grid">
          <div className="card" style={{ maxHeight: 680, overflow: "auto" }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
              <div className="ct" style={{ margin: 0, flex: 1 }}>SESSIONS</div>
              <button className="tbtn" onClick={newChat} disabled={sending}>新建</button>
            </div>
            <div style={{ display: "grid", gap: 4 }}>
              {sessions.map((s) => (
                <button key={s.id} className="tbtn" onClick={() => loadSession(s.id)} style={{ textAlign: "left", borderColor: s.id === activeSession?.id ? "var(--acc)" : "var(--b)", color: s.id === activeSession?.id ? "var(--acc)" : "var(--t2)", padding: "5px 8px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 10 }}>
                  {s.title || "新对话"}
                </button>
              ))}
            </div>
          </div>
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderBottom: "1px solid var(--b)", flexWrap: "wrap" }}>
              <span style={{ color: "var(--t)", fontSize: 12, flex: 1 }}>{activeSession?.title || "知识库对话"}</span>
              {activeSession && <button className="tbtn" onClick={() => archiveChat(activeSession.id)}>归档</button>}
            </div>
            <div style={{ minHeight: 420, maxHeight: 560, overflow: "auto", padding: 12, display: "grid", gap: 10 }}>
              {!messages.length && <div style={{ color: "var(--t3)", fontSize: 12 }}>直接提问，例如：「这个产品广告应该怎么打？」系统会先检索知识库，再调用本机 Hermes 生成回答，并在消息下方显示引用来源。</div>}
              {messages.map((m) => (
                <div key={m.id} style={{ justifySelf: m.role === "user" ? "end" : "start", maxWidth: "88%" }}>
                  <div style={{ border: "1px solid var(--b)", background: m.role === "user" ? "rgba(47,129,247,.13)" : "rgba(255,255,255,.03)", color: "var(--t)", padding: "9px 11px", borderRadius: 8, whiteSpace: "pre-wrap", fontSize: 12, lineHeight: 1.65 }}>{m.content}</div>
                  {m.role === "assistant" && m.citations?.length > 0 && (
                    <details style={{ marginTop: 6, color: "var(--t3)", fontSize: 10 }}>
                      <summary>引用来源 {m.citations.length}</summary>
                      <div style={{ display: "grid", gap: 5, marginTop: 6 }}>
                        {m.citations.map((c, i) => <button key={`${c.slug}-${i}`} className="tbtn" onClick={() => openSlug(c.slug)} style={{ textAlign: "left" }}>{c.slug}<br /><span style={{ color: "var(--t3)" }}>{c.snippet?.slice(0, 160)}</span></button>)}
                      </div>
                    </details>
                  )}
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, padding: 10, borderTop: "1px solid var(--b)" }}>
              <textarea className="inp" value={chatInput} onChange={(e) => setChatInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) sendChat(); }} placeholder="输入问题，Ctrl/⌘ + Enter 发送" style={{ minHeight: 54, flex: 1, resize: "vertical" }} />
              <button className="tbtn" onClick={sendChat} disabled={sending || !chatInput.trim()}>{sending ? "发送中..." : "发送"}</button>
            </div>
          </div>
        </div>
      )}

      {tab === "upload" && (
        <div className="g2" style={{ alignItems: "start" }}>
          <div className="card">
            <div className="ct">ADD KNOWLEDGE</div>
            <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
              <button className={"tbtn" + (uploadMode === "paste" ? " active" : "")} onClick={() => setUploadMode("paste")}>粘贴文本</button>
              <button className={"tbtn" + (uploadMode === "file" ? " active" : "")} onClick={() => setUploadMode("file")}>上传文件</button>
              <button className={"tbtn" + (uploadMode === "url" ? " active" : "")} onClick={() => setUploadMode("url")}>URL 抓取</button>
            </div>
            {uploadMode === "paste" ? (
              <div style={{ display: "grid", gap: 10 }}>
                <MiniAlert kind="info">直接粘贴正文即可。后端会自动识别标题、目录、标签和摘要，目录不存在会在 /root/brain 下安全新建；前端不传目录，避免路径误写。</MiniAlert>
                <textarea className="inp" value={pasteText} onChange={(e) => setPasteText(e.target.value)} placeholder="粘贴运营笔记、售后模板、供应商信息、广告复盘等正文..." style={{ minHeight: 260, resize: "vertical", lineHeight: 1.65 }} />
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span style={{ color: "var(--t3)", fontSize: 10 }}>{pasteText.trim().length.toLocaleString()} chars</span>
                  <button className="tbtn" onClick={doIngestText} disabled={saving || !pasteText.trim()}>{saving ? "分析入库中..." : "自动分析并入库"}</button>
                </div>
              </div>
            ) : uploadMode === "url" ? (
              <div style={{ display: "grid", gap: 10 }}>
                <MiniAlert kind="info">粘贴网页链接，系统会自动抓取内容、提取正文、分析整理后入库。</MiniAlert>
                <input className="inp" value={urlInput} onChange={(e) => setUrlInput(e.target.value)} placeholder="https://..." />
                <button className="tbtn" onClick={doIngestUrl} disabled={saving || !urlInput.trim()}>{saving ? "抓取分析中..." : "抓取并入库"}</button>
              </div>
            ) : (
              <div style={{ display: "grid", gap: 10 }}>
                <input className="inp" type="file" accept=".md,.txt,.csv,.json,.xlsx,.pdf" onChange={(e) => setUploadFile(e.target.files?.[0] || null)} />
                <input className="inp" value={uploadTitle} onChange={(e) => setUploadTitle(e.target.value)} placeholder="标题，可留空使用文件名" />
                <select className="inp" value={uploadCategory} onChange={(e) => setUploadCategory(e.target.value)}>
                  {CATEGORIES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                <MiniAlert kind="info">支持 md/txt/csv/json/xlsx/pdf，单文件 10MB。上传后会转为 Markdown 并导入 GBrain。</MiniAlert>
                <button className="tbtn" onClick={doUpload} disabled={saving}>{saving ? "上传导入中..." : "上传并导入"}</button>
              </div>
            )}
          </div>
          <div className="card">
            <div className="ct">RESULT / HISTORY</div>
            {uploadResult ? (
              <div style={{ display: "grid", gap: 8 }}>
                <MiniAlert kind={uploadResult.import_status === "ok" ? "ok" : "warn"}>保存路径：{uploadResult.saved_path}<br />导入状态：{uploadResult.import_status}</MiniAlert>
                {uploadResult.analysis && (
                  <div className="card" style={{ padding: 10, background: "rgba(255,255,255,.025)" }}>
                    <div style={{ color: "var(--t)", fontSize: 12, marginBottom: 6 }}>{uploadResult.analysis.title}</div>
                    <div style={{ color: "var(--t2)", fontSize: 10, lineHeight: 1.7 }}>
                      目录：{uploadResult.analysis.directory} · 类型：{uploadResult.analysis.content_type} · 来源：{uploadResult.analysis.source} · 置信度：{Math.round((uploadResult.analysis.confidence || 0) * 100)}%
                    </div>
                    <div style={{ marginTop: 6, display: "flex", gap: 5, flexWrap: "wrap" }}>{uploadResult.analysis.tags?.map((tag) => <span key={tag} className="tag tg">{tag}</span>)}</div>
                    <div style={{ color: "var(--t2)", fontSize: 11, lineHeight: 1.7, marginTop: 8 }}>{uploadResult.analysis.summary}</div>
                  </div>
                )}
                {uploadResult.warnings.length > 0 && <MiniAlert kind="warn">{uploadResult.warnings.join("\n")}</MiniAlert>}
                <pre style={{ whiteSpace: "pre-wrap", color: "var(--t2)", fontSize: 11, lineHeight: 1.7, maxHeight: 360, overflow: "auto" }}>{uploadResult.markdown_preview}</pre>
              </div>
            ) : <div style={{ color: "var(--t3)", fontSize: 11 }}>入库后这里显示自动识别结果和 Markdown 预览。</div>}
            <div style={{ marginTop: 12, display: "grid", gap: 5 }}>
              {uploadHistory.slice(0, 8).map((u) => <button key={u.id} className="tbtn" onClick={() => openFile(u.saved_path)} style={{ textAlign: "left" }}>{u.saved_path} <span style={{ color: "var(--t3)" }}>· {fmtBytes(u.size)} · {u.import_status}</span></button>)}
            </div>
          </div>
        </div>
      )}

      {tab === "overview" && (
        <div>
          <div className="g4" style={{ marginBottom: 10 }}>
            <Stat label="Pages" value={stats?.pages ?? "-"} tone="var(--acc)" />
            <Stat label="Chunks" value={stats?.chunks ?? "-"} />
            <Stat label="Embedded" value={stats?.embedded ?? "-"} tone={(stats?.embedded ?? 0) > 0 ? "var(--acc)" : "var(--amber)"} />
            <Stat label="Files" value={files.length} />
          </div>
          <div className="g2">
            <div className="card"><div className="ct">SYSTEM</div><table className="tbl"><tbody>
              <tr><td>Brain Root</td><td>{overview?.brain_root ?? "/root/brain"}</td></tr>
              <tr><td>GBrain</td><td>{overview?.gbrain_bin ?? "/usr/local/bin/gbrain"}</td></tr>
              <tr><td>Search Mode</td><td>{overview?.search_mode ?? "-"}</td></tr>
              <tr><td>Doctor</td><td>{overview?.doctor_status ?? "-"}</td></tr>
              <tr><td>Git Dirty</td><td>{overview?.git_dirty ? <span className="cell-warn">有未提交改动</span> : <span className="cell-good">干净</span>}</td></tr>
            </tbody></table></div>
            <div className="card"><div className="ct">BY TYPE</div>{Object.entries(stats?.by_type ?? {}).length ? <table className="tbl"><tbody>{Object.entries(stats?.by_type ?? {}).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v}</td></tr>)}</tbody></table> : <div style={{ color: "var(--t3)", fontSize: 11 }}>暂无类型统计</div>}</div>
          </div>
        </div>
      )}

      {tab === "search" && (
        <div>
          <div className="card" style={{ marginBottom: 10 }}><div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input className="inp" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && doSearch()} placeholder="搜索运营知识、ASIN 笔记、广告策略..." style={{ flex: 1, minWidth: 220 }} />
            <select className="inp" value={mode} onChange={(e) => setMode(e.target.value as "search" | "query")} style={{ width: 120 }}><option value="search">search</option><option value="query">query</option></select>
            <button className="tbtn" onClick={doSearch} disabled={loading}>{loading ? "搜索中..." : "搜索"}</button>
          </div></div>
          <div style={{ display: "grid", gap: 10 }}>
            {results.map((r, i) => <ResultCard key={`${r.slug}-${i}`} item={r} onOpen={openSlug} />)}
            {!results.length && rawResult && <pre className="card" style={{ whiteSpace: "pre-wrap", color: "var(--t2)", fontSize: 11, lineHeight: 1.7 }}>{rawResult}</pre>}
            {!results.length && !rawResult && <div className="card" style={{ color: "var(--t3)", fontSize: 11 }}>输入关键词后开始搜索。</div>}
          </div>
        </div>
      )}

      {tab === "pages" && (
        <div className="g2" style={{ alignItems: "start" }}>
          <div className="card" style={{ maxHeight: 620, overflow: "auto" }}>
            <div className="ct">FILES ({files.length})</div>
            <input className="inp" placeholder="筛选..." id="brain-filter" style={{ marginBottom: 8 }} onChange={(e) => { (e.target as any)._v = e.target.value; e.target.closest('.card')?.querySelectorAll('[data-file]').forEach((el: any) => { el.style.display = el.dataset.file.includes(e.target.value) ? '' : 'none'; }); }} />
            {(() => {
              const grouped: Record<string, typeof files> = {};
              files.forEach((f) => { (grouped[f.category] ??= []).push(f); });
              return Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).map(([cat, items]) => (
                <div key={cat} style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 9, color: "var(--t3)", letterSpacing: ".08em", textTransform: "uppercase", marginBottom: 4, paddingBottom: 3, borderBottom: "1px solid var(--b)" }}>{cat} ({items.length})</div>
                  <div style={{ display: "grid", gap: 3 }}>
                    {items.map((f) => (
                      <div key={f.path} data-file={f.path + " " + f.name} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <button className="tbtn" onClick={() => openFile(f.path)} style={{ flex: 1, textAlign: "left", color: f.path === (selectedFile?.path) ? "var(--acc)" : "var(--t2)", padding: "4px 8px", overflow: "hidden" }}>
                          <div style={{ fontSize: 10, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{f.name}</div>
                          {f.summary && <div style={{ fontSize: 9, color: "var(--t3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{f.summary}</div>}
                        </button>
                        <button className="tbtn" onClick={async () => { if (!await confirm({ title: "删除文件", message: `确定删除 ${f.path}？\n此操作不可恢复。`, confirmText: "删除", danger: true })) return; try { await brainFileDelete(f.path); await loadFiles(); setFlash("已删除"); if (selectedFile?.path === f.path) { setContent(""); setSelectedPath(""); } } catch (e: any) { setErr(e?.response?.data?.detail ?? "删除失败"); } }} style={{ color: "var(--red)", padding: "4px 6px", fontSize: 9, flexShrink: 0 }}>✕</button>
                      </div>
                    ))}
                  </div>
                </div>
              ));
            })()}
          </div>
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderBottom: "1px solid var(--b)", flexWrap: "wrap" }}>
              <span style={{ color: "var(--t)", fontSize: 11, flex: 1, minWidth: 180 }}>{selectedFile?.path ?? (selectedPath || "未选择文件")}</span>
              <button className="tbtn" onClick={() => save(false)} disabled={saving}>{saving ? "保存中..." : "保存"}</button>
              <button className="tbtn" onClick={() => save(true)} disabled={saving}>{saving ? "导入中..." : "保存并导入"}</button>
            </div>
            <textarea className="inp" value={content} onChange={(e) => setContent(e.target.value)} placeholder="# Markdown 内容" style={{ minHeight: 360, border: "none", borderRadius: 0, resize: "vertical", fontSize: 12, lineHeight: 1.65 }} />
            <div style={{ borderTop: "1px solid var(--b)", padding: 10 }}><div className="ct">PREVIEW</div><pre style={{ whiteSpace: "pre-wrap", color: "var(--t2)", fontSize: 11, lineHeight: 1.7, maxHeight: 240, overflow: "auto" }}>{content || "暂无内容"}</pre></div>
          </div>
        </div>
      )}

      {tab === "templates" && <div className="g3">{TEMPLATES.map((tpl) => <div key={tpl.key} className="card"><div style={{ fontSize: 13, color: "var(--t)", marginBottom: 8 }}>{tpl.label}</div><div style={{ color: "var(--t3)", fontSize: 10, lineHeight: 1.6, marginBottom: 10 }}>{tpl.path}</div><button className="tbtn" onClick={() => createTemplate(tpl)}>使用模板</button></div>)}</div>}

      {tab === "settings" && (
        <div className="g2">
          <div className="card"><div className="ct">PATHS</div><table className="tbl"><tbody>
            <tr><td>Brain Root</td><td>{overview?.brain_root}</td></tr>
            <tr><td>GBrain Bin</td><td>{overview?.gbrain_bin}</td></tr>
            <tr><td>Embedding</td><td>{embedOn ? <span className="cell-good">已配置{overview?.embed_provider ? `（${overview.embed_provider}）` : ""}</span> : <span className="cell-warn">未配置（关键词检索）</span>}</td></tr>
            <tr><td>Hermes Chat</td><td>{chatStatus?.configured ? <span className="cell-good">已接入</span> : <span className="cell-warn">不可用</span>}</td></tr>
            <tr><td>Chat Engine</td><td>{chatStatus?.model || "Hermes Agent"}</td></tr>
            <tr><td>Hermes Bin</td><td>{chatStatus?.hermes_bin || "-"}</td></tr>
          </tbody></table></div>
          <div className="card"><div className="ct">ACTIONS</div><div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="tbtn" onClick={runDoctor} disabled={loading}>运行 Doctor</button>
            <button className="tbtn" onClick={async () => { setLoading(true); try { const r = await brainImport(); setFlash(r.raw || "导入完成"); await loadOverview(); } catch (e: any) { setErr(e?.response?.data?.detail ?? e.message); } finally { setLoading(false); } }} disabled={loading}>重新导入 /root/brain</button>
          </div></div>
        </div>
      )}

      <style>{`@media (max-width: 760px) { .brain-chat-grid { grid-template-columns: 1fr !important; } }`}</style>
    </div>
  );
}
