import { useCallback, useEffect, useMemo, useState } from "react";
import { useConfirm } from "../../components/ConfirmDialog";
import BrainMarkdown from "./BrainMarkdown";
import SheetSelect from "../../components/SheetSelect";
import KnowledgeGovernancePanel from "./KnowledgeGovernance";
import {
  brainChatCreate,
  brainChatGet,
  brainChatSendStream,
  brainChatDeleteMessage,
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

type Tab = "governance" | "chat" | "upload" | "search" | "pages" | "templates" | "overview" | "settings";

// 高频操作平铺显示；低频管理页收进「更多▾」溢出菜单
const PRIMARY_TABS: { key: Tab; label: string }[] = [
  { key: "chat", label: "对话" },
  { key: "upload", label: "上传" },
  { key: "search", label: "搜索" },
  { key: "pages", label: "页面" },
];

const MORE_TABS: { key: Tab; label: string }[] = [
  { key: "governance", label: "治理中心" },
  { key: "overview", label: "概览" },
  { key: "settings", label: "设置" },
];

// 检索范围（GBrain 知识分类，对应后端 ALLOWED_CATEGORIES）
const SCOPE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部知识" },
  { value: "amazon", label: "Amazon 运营" },
  { value: "products", label: "产品" },
  { value: "market", label: "市场" },
  { value: "ads", label: "广告" },
  { value: "compliance", label: "合规" },
  { value: "suppliers", label: "供应商" },
  { value: "inbox", label: "收件箱" },
];

// 空状态的 Amazon 运营快捷提问（点击直接发送，先检索知识库再让 Hermes 作答）
const QUICK_PROMPTS: string[] = [
  "这个产品广告应该怎么打？给出精准/词组/广泛和否词的初始结构。",
  "帮我梳理这个 Listing 的 CTR/CVR 优化点（主图、标题、五点、A+）。",
  "围绕核心词给一份长尾词与关键词布局策略。",
  "售后/差评场景下，有哪些合规话术和风险规避要点？",
  "根据知识库里的供应商/采购信息，整理一份比价与跟进清单。",
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

const ALL_TABS = [...PRIMARY_TABS, ...MORE_TABS];

function getInitialTab(): Tab {
  const p = new URLSearchParams(window.location.search);
  const t = p.get("tab") as Tab | null;
  return ALL_TABS.some((x) => x.key === t) ? (t as Tab) : "chat";
}

export default function Brain() {
  const confirm = useConfirm();
  const [tab, setTabState] = useState<Tab>(getInitialTab);
  const [overview, setOverview] = useState<BrainOverview | null>(null);
  const [files, setFiles] = useState<BrainFileItem[]>([]);
  const [collapsedCats, setCollapsedCats] = useState<Record<string, boolean>>({});
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
  const [savingKb, setSavingKb] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [sessionFilter, setSessionFilter] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [chatScope, setChatScope] = useState("");
  const [isMobile, setIsMobile] = useState(() => window.innerWidth <= 760);
  const [sessionSheetOpen, setSessionSheetOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

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

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth <= 760);
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  const selectedFile = useMemo(() => files.find((f) => f.path === selectedPath), [files, selectedPath]);
  const stats = overview?.stats;
  const embedOn = overview && (overview.embed_configured ?? overview.openai_configured);
  const noEmbed = overview && !embedOn;
  // The front door is IvyeaAgent; the legacy GBrain readiness/embedding notices
  // (Ollama, gbrain bin, version-compat) only matter when we've degraded to it.
  const legacyGbrainMode = chatStatus?.provider !== "ivyea-agent";

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

  const runStream = async (sessionId: string, body: { content?: string; regenerate?: boolean; category?: string }, tmpAsst: string, tmpUser?: string) => {
    await brainChatSendStream(sessionId, body, (evt) => {
      if (evt.type === "start") {
        setMessages((prev) => prev.map((m) => {
          if (tmpUser && m.id === tmpUser && evt.user_message) return evt.user_message;
          if (m.id === tmpAsst) return { ...m, citations: evt.citations || [] };
          return m;
        }));
      } else if (evt.type === "token") {
        setMessages((prev) => prev.map((m) => (m.id === tmpAsst ? { ...m, content: m.content + evt.text } : m)));
      } else if (evt.type === "done") {
        setMessages((prev) => prev.map((m) => (m.id === tmpAsst ? { ...evt.assistant_message, _engine: evt.engine, _citCount: evt.citations_count } : m)));
      } else if (evt.type === "error") {
        throw new Error(evt.detail);
      }
    });
  };

  const sendChat = async (override?: string) => {
    const text = (override ?? chatInput).trim();
    if (!text || !activeSession || sending) return;
    const sid = activeSession.id;
    setSending(true);
    setErr(null);
    setChatInput("");
    const tmpUser = `local-u-${Date.now()}`;
    const tmpAsst = `local-a-${Date.now()}`;
    const now = new Date().toISOString();
    setMessages((prev) => [
      ...prev,
      { id: tmpUser, session_id: sid, role: "user", content: text, citations: [], created_at: now },
      { id: tmpAsst, session_id: sid, role: "assistant", content: "", citations: [], created_at: now },
    ]);
    try {
      await runStream(sid, { content: text, category: chatScope || undefined }, tmpAsst, tmpUser);
      const list = await brainChatSessions();
      setSessions(list.sessions);
    } catch (e: any) {
      setErr(e?.message ?? "发送失败");
      setMessages((prev) => prev.filter((m) => m.id !== tmpAsst && m.id !== tmpUser));
      setChatInput(text);
    } finally {
      setSending(false);
    }
  };

  const regenerate = async () => {
    if (!activeSession || sending) return;
    const sid = activeSession.id;
    const lastAsst = [...messages].reverse().find((m) => m.role === "assistant" && !m.id.startsWith("local-"));
    if (!lastAsst) return;
    setSending(true);
    setErr(null);
    const tmpAsst = `local-a-${Date.now()}`;
    setMessages((prev) => [
      ...prev.filter((m) => m.id !== lastAsst.id),
      { id: tmpAsst, session_id: sid, role: "assistant", content: "", citations: lastAsst.citations, created_at: new Date().toISOString() },
    ]);
    try {
      await runStream(sid, { regenerate: true, category: chatScope || undefined }, tmpAsst);
    } catch (e: any) {
      setErr(e?.message ?? "重新生成失败");
      try { await loadSession(sid); } catch { /* keep error */ }
    } finally {
      setSending(false);
    }
  };

  const deleteMessage = async (m: BrainChatMessage) => {
    if (m.id.startsWith("local-")) return;
    const ok = await confirm({ title: "删除该消息", message: "删除后无法恢复。", confirmText: "删除", danger: true });
    if (!ok) return;
    try {
      await brainChatDeleteMessage(m.id);
      setMessages((prev) => prev.filter((x) => x.id !== m.id));
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "删除失败");
    }
  };

  const copyMessage = (m: BrainChatMessage) => {
    navigator.clipboard?.writeText(m.content).then(() => {
      setCopiedId(m.id);
      setTimeout(() => setCopiedId((id) => (id === m.id ? null : id)), 1500);
    });
  };

  const beginRename = (s: BrainChatSession) => {
    setRenamingId(s.id);
    setRenameValue(s.title || "");
  };

  const commitRename = async (sessionId: string) => {
    const title = renameValue.trim();
    setRenamingId(null);
    const current = sessions.find((s) => s.id === sessionId);
    if (!title || title === (current?.title || "")) return;
    try {
      await brainChatUpdate(sessionId, { title });
      setSessions((prev) => prev.map((s) => (s.id === sessionId ? { ...s, title } : s)));
      if (activeSession?.id === sessionId) setActiveSession((a) => (a ? { ...a, title } : a));
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "重命名失败");
    }
  };

  const quickAsk = (text: string) => {
    if (sending || !activeSession) return;
    void sendChat(text);
  };

  const saveAsKnowledge = async (m: BrainChatMessage) => {
    if (savingKb) return;
    setSavingKb(m.id);
    setErr(null);
    try {
      const r = await brainIngestText(m.content, true);
      setFlash(`已存入知识库：${r.saved_path || "已保存"}`);
      await Promise.all([loadFiles(), loadOverview()]);
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? e.message ?? "存入知识库失败");
    } finally {
      setSavingKb(null);
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
    <div className={tab === "chat" ? "brain-page-chat" : undefined}>
      <div className="ptitle">/ 知识库工作台</div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
        <span className="tag tg">IVYEA KNOWLEDGE</span>
        {!isMobile && <span style={{ color: "var(--t2)", fontSize: 11 }}>{tab === "governance" ? "官方来源审核、覆盖、时效、质量和冲突治理" : "对话 / 搜索 / 上传均由 IvyeaAgent 内置知识库承载；仍有旧 ~/brain 内容可在右下角 IvyeaAgent 一键迁移进来"}</span>}
        {tab !== "governance" && <button className="tbtn" onClick={() => { loadOverview(); loadFiles(); loadUploads(); loadChat(); }} style={{ marginLeft: "auto" }}>刷新</button>}
      </div>

      {err && tab !== "governance" && <div style={{ marginBottom: 10 }}><MiniAlert kind="bad">{err}</MiniAlert></div>}
      {legacyGbrainMode && tab !== "governance" && overview?.ready && overview.ready.version_compatible === false && (
        <div style={{ marginBottom: 10 }}><MiniAlert kind="bad">{overview.ready.hint || "GBrain 版本不兼容，知识库未就绪。"}请到「系统配置 → 系统状态」对 GBrain 执行「安装/修复」（会清掉旧版本并装回兼容版）。</MiniAlert></div>
      )}
      {legacyGbrainMode && tab !== "governance" && overview?.ready && overview.ready.db_ready && overview.ready.actions?.length > 0 && (
        <div style={{ marginBottom: 10 }}><MiniAlert kind="ok">已自动配置：{overview.ready.actions.join("；")}。</MiniAlert></div>
      )}
      {legacyGbrainMode && tab !== "governance" && overview?.ready && overview.ready.db_ready && !overview.ready.embed_ready && overview.ready.hint && (
        <div style={{ marginBottom: 10 }}><MiniAlert kind="info">{overview.ready.hint}</MiniAlert></div>
      )}
      {flash && tab !== "governance" && <div style={{ marginBottom: 10 }}><MiniAlert kind="info"><pre style={{ whiteSpace: "pre-wrap", fontFamily: "var(--font)" }}>{flash}</pre></MiniAlert></div>}
      {legacyGbrainMode && tab !== "governance" && noEmbed && <div style={{ marginBottom: 10 }}><MiniAlert kind="warn">未配置 Embedding：当前以关键词检索为主（功能正常）。如需语义检索，<a href="/hub-settings" style={{ color: "var(--acc)" }}>前往系统配置 → 智能体 → 知识库语义检索 →</a> 选择服务商（Ollama 本地免费）。</MiniAlert></div>}
      {chatStatus && !chatStatus.configured && tab === "chat" && <div style={{ marginBottom: 10 }}><MiniAlert kind="warn">对话引擎未就绪：请确认本机 IvyeaAgent 服务在运行，或在「系统配置 → 全局兜底大模型」配置一个文本模型。搜索、上传、页面仍可用。</MiniAlert></div>}

      {/* Outer row does NOT clip overflow, so the 「更多」dropdown can escape.
          Only the inner primary-tab strip scrolls horizontally. */}
      <div style={{ display: "flex", alignItems: "flex-end", borderBottom: "1px solid var(--b)", marginBottom: 14 }}>
        <div style={{ display: "flex", gap: 0, overflowX: "auto", flex: 1 }}>
          {PRIMARY_TABS.map((t) => <button key={t.key} className={"tab" + (tab === t.key ? " active" : "")} onClick={() => setTab(t.key)}>{t.label}</button>)}
        </div>
        <div style={{ position: "relative", flexShrink: 0 }}>
          <button
            className={"tab" + (MORE_TABS.some((t) => t.key === tab) ? " active" : "")}
            onClick={() => setMoreOpen((v) => !v)}
          >
            {MORE_TABS.find((t) => t.key === tab) ? `更多 · ${MORE_TABS.find((t) => t.key === tab)!.label}` : "更多"} ▾
          </button>
          {moreOpen && (
            <>
              <div onClick={() => setMoreOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 40 }} />
              <div style={{ position: "absolute", top: "calc(100% + 4px)", right: 0, zIndex: 41, minWidth: 150, padding: 4, display: "grid", gap: 2, background: "var(--bg1)", border: "1px solid var(--b)", borderRadius: "var(--r)", backdropFilter: "blur(16px)", WebkitBackdropFilter: "blur(16px)", boxShadow: "0 8px 24px rgba(0,0,0,.28)" }}>
                {MORE_TABS.map((t) => (
                  <button key={t.key} className="tbtn" style={{ textAlign: "left", width: "100%", borderColor: "transparent", color: tab === t.key ? "var(--acc)" : undefined, background: tab === t.key ? "var(--bg3)" : undefined }} onClick={() => { setTab(t.key); setMoreOpen(false); }}>{t.label}</button>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {tab === "governance" && <KnowledgeGovernancePanel />}

      {tab === "chat" && (
        <>
          {/* Mobile: sessions bottom sheet */}
          {isMobile && sessionSheetOpen && (
            <div style={{ position: "fixed", inset: 0, zIndex: 897, background: "rgba(0,0,0,.5)" }} onClick={() => setSessionSheetOpen(false)} />
          )}
          {isMobile && (
            <div style={{
              position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 898,
              maxHeight: "60vh", background: "var(--bg1)",
              borderRadius: "16px 16px 0 0",
              display: "flex", flexDirection: "column",
              boxShadow: "0 -4px 32px rgba(0,0,0,.4)",
              transform: sessionSheetOpen ? "translateY(0)" : "translateY(110%)",
              transition: "transform .25s cubic-bezier(.4,0,.2,1)",
            }}>
              <div style={{ display: "flex", justifyContent: "center", padding: "10px 0 4px", flexShrink: 0 }}>
                <div style={{ width: 36, height: 4, borderRadius: 2, background: "var(--b2)" }} />
              </div>
              <div style={{ display: "flex", alignItems: "center", padding: "2px 16px 10px", flexShrink: 0, borderBottom: "1px solid var(--b)" }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: "var(--t)", flex: 1 }}>会话列表</span>
                <button className="tbtn" onClick={newChat} disabled={sending} style={{ marginRight: 8 }}>＋ 新建</button>
                <button onClick={() => setSessionSheetOpen(false)} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)", fontSize: 18, padding: "0 2px", lineHeight: 1 }}>✕</button>
              </div>
              <div style={{ overflowY: "auto", flex: 1 }}>
                {sessions.map((s) => (
                  <div
                    key={s.id}
                    onClick={() => { loadSession(s.id); setSessionSheetOpen(false); }}
                    style={{
                      padding: "12px 16px", cursor: "pointer", borderBottom: "1px solid var(--b)",
                      background: s.id === activeSession?.id ? "color-mix(in srgb, var(--acc) 10%, transparent)" : undefined,
                      display: "flex", alignItems: "center", gap: 10, transition: "background .12s",
                    }}
                  >
                    <span style={{ flex: 1, fontSize: 13, color: s.id === activeSession?.id ? "var(--acc)" : "var(--t)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: s.id === activeSession?.id ? 600 : 400 }}>{s.title || "新对话"}</span>
                    <button onClick={(e) => { e.stopPropagation(); archiveChat(s.id); setSessionSheetOpen(false); }} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)", fontSize: 11, padding: "2px 6px", flexShrink: 0 }}>归档</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "160px minmax(0, 1fr)", gap: 10, minHeight: 320, flex: 1 }} className="brain-chat-grid">
            {/* Sessions panel — desktop only */}
            {!isMobile && (
              <div className="card" style={{ overflow: "auto" }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                  <div className="ct" style={{ margin: 0, flex: 1 }}>SESSIONS</div>
                  <button className="tbtn" onClick={newChat} disabled={sending}>新建</button>
                </div>
                <input className="inp" value={sessionFilter} onChange={(e) => setSessionFilter(e.target.value)} placeholder="搜索会话..." style={{ marginBottom: 8, padding: "4px 8px", fontSize: 10 }} />
                <div style={{ display: "grid", gap: 4 }}>
                  {sessions.filter((s) => !sessionFilter.trim() || (s.title || "新对话").toLowerCase().includes(sessionFilter.trim().toLowerCase())).map((s) => (
                    renamingId === s.id ? (
                      <input
                        key={s.id}
                        className="inp"
                        autoFocus
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onBlur={() => commitRename(s.id)}
                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commitRename(s.id); } else if (e.key === "Escape") { setRenamingId(null); } }}
                        style={{ padding: "4px 7px", fontSize: 10, borderColor: "var(--acc)" }}
                      />
                    ) : (
                      <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 2, border: "1px solid " + (s.id === activeSession?.id ? "var(--acc)" : "var(--b)"), borderRadius: 5, overflow: "hidden" }}>
                        <button className="tbtn" onClick={() => loadSession(s.id)} title={s.title || "新对话"} style={{ flex: 1, minWidth: 0, textAlign: "left", border: "none", color: s.id === activeSession?.id ? "var(--acc)" : "var(--t2)", padding: "5px 8px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 10 }}>
                          {s.title || "新对话"}
                        </button>
                        <button onClick={(e) => { e.stopPropagation(); beginRename(s); }} title="重命名" style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)", fontSize: 11, padding: "2px 6px", flexShrink: 0 }}>✎</button>
                      </div>
                    )
                  ))}
                  {sessions.length > 0 && sessions.filter((s) => !sessionFilter.trim() || (s.title || "新对话").toLowerCase().includes(sessionFilter.trim().toLowerCase())).length === 0 && (
                    <div style={{ color: "var(--t3)", fontSize: 10, padding: "4px 2px" }}>无匹配会话</div>
                  )}
                </div>
              </div>
            )}

            {/* Chat panel */}
            <div className="card" style={{ padding: 0, overflow: "hidden", display: "flex", flexDirection: "column", minHeight: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderBottom: "1px solid var(--b)", flexWrap: "wrap", flexShrink: 0 }}>
                <span style={{ color: "var(--t)", fontSize: 12, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{activeSession?.title || "知识库对话"}</span>
                {isMobile && (
                  <button className="tbtn" onClick={() => setSessionSheetOpen(true)}>≡ 会话</button>
                )}
                {activeSession && <button className="tbtn" onClick={() => archiveChat(activeSession.id)}>归档</button>}
              </div>
              <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 12, display: "grid", gap: 10, alignContent: "start" }}>
                {!messages.length && (
                  <div style={{ display: "grid", gap: 10 }}>
                    <div style={{ color: "var(--t3)", fontSize: 12 }}>直接提问，系统会先检索知识库，再调用本机 Hermes 生成回答，并在消息下方显示引用来源。或从下面的常用问题开始：</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {QUICK_PROMPTS.map((p, i) => (
                        <button key={i} className="tbtn" onClick={() => quickAsk(p)} disabled={sending} style={{ textAlign: "left", padding: "6px 10px", fontSize: 11, maxWidth: 360, whiteSpace: "normal", lineHeight: 1.5 }}>
                          {p}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {(() => {
                  const lastAssistantId = [...messages].reverse().find((x) => x.role === "assistant" && !x.id.startsWith("local-"))?.id;
                  return messages.map((m) => (
                  <div key={m.id} style={{ justifySelf: m.role === "user" ? "end" : "start", maxWidth: m.role === "user" ? "88%" : "94%" }}>
                    <div style={{ border: "1px solid var(--b)", background: m.role === "user" ? "rgba(47,129,247,.13)" : "rgba(255,255,255,.03)", color: "var(--t)", padding: "9px 11px", borderRadius: 8, fontSize: 12, lineHeight: 1.65 }}>
                      {m.role === "assistant"
                        ? (m.content ? <BrainMarkdown>{m.content}</BrainMarkdown> : <span style={{ color: "var(--t3)" }}>{sending ? "生成中…" : "（空回答）"}</span>)
                        : <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>}
                    </div>
                    {m.role === "assistant" && m.citations?.length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 6, alignItems: "center" }}>
                        <span style={{ color: "var(--t3)", fontSize: 10 }}>来源</span>
                        {m.citations.map((c, i) => (
                          <button key={`${c.slug}-${i}`} className="tbtn" onClick={() => c.slug && openSlug(c.slug)} title={c.snippet?.slice(0, 200)} style={{ padding: "1px 7px", fontSize: 10, maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {c.slug || c.snippet?.slice(0, 24) || "片段"}
                          </button>
                        ))}
                      </div>
                    )}
                    {m.role === "assistant" && (m as any)._engine && (
                      <div style={{ marginTop: 5, fontSize: 10, color: "var(--t3)", display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
                        <span style={{ border: "1px solid var(--b)", borderRadius: 4, padding: "0 5px" }}>
                          {(m as any)._engine === "hermes" ? "Hermes 本机模型" : "兜底大模型"}
                        </span>
                        <span>·</span>
                        <span>{(m as any)._citCount > 0 ? `检索命中知识 ${(m as any)._citCount} 条` : "未命中知识库（凭模型常识作答）"}</span>
                      </div>
                    )}
                    {m.role === "assistant" && !m.id.startsWith("local-") && (
                      <div style={{ display: "flex", gap: 6, marginTop: 5, flexWrap: "wrap" }}>
                        <button className="tbtn" onClick={() => copyMessage(m)} style={{ padding: "1px 8px", fontSize: 10 }}>{copiedId === m.id ? "已复制" : "复制"}</button>
                        <button className="tbtn" onClick={() => saveAsKnowledge(m)} disabled={savingKb === m.id} style={{ padding: "1px 8px", fontSize: 10 }}>{savingKb === m.id ? "存入中..." : "存为知识"}</button>
                        {m.id === lastAssistantId && <button className="tbtn" onClick={regenerate} disabled={sending} style={{ padding: "1px 8px", fontSize: 10 }}>重新生成</button>}
                        <button className="tbtn" onClick={() => deleteMessage(m)} style={{ padding: "1px 8px", fontSize: 10, color: "var(--red)" }}>删除</button>
                      </div>
                    )}
                  </div>
                  ));
                })()}
              </div>
              <div style={{ display: "flex", gap: 8, padding: 10, borderTop: "1px solid var(--b)", flexShrink: 0, alignItems: "stretch" }}>
                <textarea className="inp" value={chatInput} onChange={(e) => setChatInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); sendChat(); } }} placeholder="输入问题，Enter 发送（Shift+Enter 换行）" style={{ minHeight: 54, maxHeight: 140, flex: 1, resize: "vertical" }} />
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <SheetSelect className="inp" value={chatScope} onChange={setChatScope} title="限定检索范围" style={{ padding: "4px 6px", fontSize: 10 }}
                    options={SCOPE_OPTIONS} />
                  <button className="tbtn" onClick={() => sendChat()} disabled={sending || !chatInput.trim()} style={{ flex: 1 }}>{sending ? "发送中..." : "发送"}</button>
                </div>
              </div>
            </div>
          </div>
        </>
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
                <MiniAlert kind="info">直接粘贴正文即可。后端会自动识别标题、目录、标签和摘要，目录不存在会在知识库根目录下安全新建；前端不传目录，避免路径误写。</MiniAlert>
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
                <SheetSelect className="inp" value={uploadCategory} onChange={setUploadCategory} title="选择分类"
                  options={CATEGORIES.map(([k, v]) => ({ value: k, label: v }))} />
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
                {(uploadResult.warnings?.length ?? 0) > 0 && <MiniAlert kind="warn">{uploadResult.warnings!.join("\n")}</MiniAlert>}
                {uploadResult.markdown_preview && <pre style={{ whiteSpace: "pre-wrap", color: "var(--t2)", fontSize: 11, lineHeight: 1.7, maxHeight: 360, overflow: "auto" }}>{uploadResult.markdown_preview}</pre>}
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
          {(() => {
            const byCat: Record<string, number> = {};
            for (const f of files) { const k = String((f as any).category || "其他"); byCat[k] = (byCat[k] || 0) + 1; }
            const cats = Object.entries(byCat).sort((a, b) => b[1] - a[1]);
            return (
              <>
                <div className="g4" style={{ marginBottom: 10 }}>
                  <Stat label="知识卡片" value={files.length} tone="var(--acc)" />
                  <Stat label="分类" value={cats.length || "-"} />
                  <Stat label="引擎" value={chatStatus?.provider === "ivyea-agent" ? "IvyeaAgent" : (chatStatus?.provider || "-")} tone="var(--acc)" />
                  <Stat label="状态" value={chatStatus?.configured ? "已接入" : "不可用"} tone={chatStatus?.configured ? "var(--acc)" : "var(--amber)"} />
                </div>
                <div className="g2">
                  <div className="card"><div className="ct">知识引擎</div><table className="tbl"><tbody>
                    <tr><td>前门</td><td>{chatStatus?.provider === "ivyea-agent" ? <span className="cell-good">IvyeaAgent 内置知识库</span> : <span className="cell-warn">回退：{chatStatus?.provider || "未就绪"}</span>}</td></tr>
                    <tr><td>对话 / 检索模型</td><td>{chatStatus?.model || "-"}</td></tr>
                    <tr><td>治理</td><td><a onClick={() => setTab("governance")} style={{ color: "var(--acc)", cursor: "pointer" }}>治理中心 →</a></td></tr>
                  </tbody></table></div>
                  <div className="card"><div className="ct">按分类</div>{cats.length ? <table className="tbl"><tbody>{cats.map(([k, v]) => <tr key={k}><td>{k}</td><td>{v}</td></tr>)}</tbody></table> : <div style={{ color: "var(--t3)", fontSize: 11 }}>暂无卡片</div>}</div>
                </div>
              </>
            );
          })()}
        </div>
      )}

      {tab === "search" && (
        <div>
          <div className="card" style={{ marginBottom: 10 }}><div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input className="inp" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && doSearch()} placeholder="搜索运营知识、ASIN 笔记、广告策略..." style={{ flex: 1, minWidth: 220 }} />
            <SheetSelect className="inp" value={mode} onChange={(v) => setMode(v as "search" | "query")} style={{ width: 120 }} title="检索模式"
              options={[{ value: "search", label: "search" }, { value: "query", label: "query" }]} />
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
            {(() => {
              const grouped: Record<string, typeof files> = {};
              files.forEach((f) => { (grouped[f.category] ??= []).push(f); });
              const cats = Object.keys(grouped).sort((a, b) => a.localeCompare(b));
              const allCollapsed = cats.length > 0 && cats.every((c) => collapsedCats[c]);
              return (
                <>
                  <div className="ct" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span>FILES ({files.length})</span>
                    {cats.length > 1 && (
                      <button className="tbtn" style={{ fontSize: 9, padding: "2px 6px" }}
                        onClick={() => {
                          const next: Record<string, boolean> = {};
                          if (!allCollapsed) cats.forEach((c) => { next[c] = true; });
                          setCollapsedCats(next);
                        }}>
                        {allCollapsed ? "全部展开" : "全部收起"}
                      </button>
                    )}
                  </div>
                  <input className="inp" placeholder="筛选..." id="brain-filter" style={{ marginBottom: 8 }} onChange={(e) => { (e.target as any)._v = e.target.value; e.target.closest('.card')?.querySelectorAll('[data-file]').forEach((el: any) => { el.style.display = el.dataset.file.includes(e.target.value) ? '' : 'none'; }); }} />
                  {cats.map((cat) => {
                    const items = grouped[cat];
                    const collapsed = !!collapsedCats[cat];
                    return (
                <div key={cat} style={{ marginBottom: 10 }}>
                  <div
                    onClick={() => setCollapsedCats((m) => ({ ...m, [cat]: !m[cat] }))}
                    style={{ fontSize: 9, color: "var(--t3)", letterSpacing: ".08em", textTransform: "uppercase", marginBottom: 4, paddingBottom: 3, borderBottom: "1px solid var(--b)", cursor: "pointer", display: "flex", alignItems: "center", gap: 5, userSelect: "none" }}>
                    <span style={{ display: "inline-block", transition: "transform .12s", transform: collapsed ? "rotate(-90deg)" : "none", fontSize: 8 }}>▼</span>
                    <span style={{ flex: 1 }}>{cat} ({items.length})</span>
                  </div>
                  {!collapsed && (
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
                  )}
                </div>
                    );
                  })}
                </>
              );
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
          <div className="card"><div className="ct">知识引擎</div><table className="tbl"><tbody>
            <tr><td>前门</td><td>{chatStatus?.provider === "ivyea-agent"
              ? <span className="cell-good">IvyeaAgent 内置知识库</span>
              : <span className="cell-warn">回退：{chatStatus?.provider || "未就绪"}</span>}</td></tr>
            <tr><td>对话 / 检索模型</td><td>{chatStatus?.model || "-"}</td></tr>
            <tr><td>知识卡片</td><td>{files.length} 张</td></tr>
            <tr><td>状态</td><td>{chatStatus?.configured ? <span className="cell-good">已接入</span> : <span className="cell-warn">不可用</span>}</td></tr>
          </tbody></table></div>
          <div className="card"><div className="ct">治理与迁移</div>
            <div style={{ color: "var(--t3)", fontSize: 11, lineHeight: 1.8, marginBottom: 10 }}>
              知识卡的审核、覆盖、时效与冲突治理请到「治理中心」。旧 <code>~/brain</code> 内容可在右下角 IvyeaAgent 面板一键迁移进统一知识库。
            </div>
            <button className="tbtn" onClick={() => setTab("governance")}>前往治理中心</button>
          </div>
        </div>
      )}

      <style>{`@media (max-width: 760px) { .brain-chat-grid { grid-template-columns: 1fr !important; } }`}</style>
    </div>
  );
}
