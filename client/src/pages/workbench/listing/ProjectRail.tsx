// 项目栏：新建 + 搜索 + 项目卡（状态点 / 进行中任务 spinner / 相对时间 / 删除）。
import { useMemo, useState } from "react";
import { Loader2, Plus, Search, Trash2 } from "lucide-react";
import { useConfirm } from "../../../components/ConfirmDialog";
import SheetSelect from "../../../components/SheetSelect";
import { marketplaceOptions } from "../../../lib/marketplaces";
import type { ProjectSummary } from "./types";

const STATUS_LABEL: Record<string, string> = {
  created: "新建",
  scraped: "已采集",
  analyzed: "已分析",
  copywritten: "有文案",
};

function relativeTime(ts: number): string {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 90) return "刚刚";
  if (diff < 3600) return `${Math.round(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.round(diff / 3600)} 小时前`;
  if (diff < 86400 * 30) return `${Math.round(diff / 86400)} 天前`;
  return new Date(ts * 1000).toLocaleDateString();
}

const JOB_LABEL: Record<string, string> = {
  scrape: "采集中",
  analyze: "分析中",
  copy: "写文案",
  plan: "策划中",
  render_image: "生图中",
  render_set: "生图中",
  review_set: "复核中",
};

interface Props {
  projects: ProjectSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: (asin: string, marketplace: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

export default function ProjectRail({ projects, activeId, onSelect, onCreate, onDelete }: Props) {
  const confirm = useConfirm();
  const [asin, setAsin] = useState("");
  const [marketplace, setMarketplace] = useState("US");
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter((p) =>
      p.asin.toLowerCase().includes(q)
      || (p.title || "").toLowerCase().includes(q)
      || p.marketplace.toLowerCase().includes(q));
  }, [projects, query]);

  async function handleCreate() {
    if (!asin.trim() || creating) return;
    setCreating(true);
    try {
      await onCreate(asin, marketplace);
      setAsin("");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="listing-sidebar lst-rail">
      <div className="card">
        <div className="lst-rail-create">
          <input
            className="lst-input"
            value={asin}
            onChange={(e) => setAsin(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void handleCreate(); }}
            placeholder="输入 ASIN 新建…"
          />
          <SheetSelect value={marketplace} onChange={setMarketplace} className="xsel-compact" flags title="选择站点"
            options={marketplaceOptions(["US", "UK", "DE", "JP", "FR", "IT", "ES", "CA", "AU"])} />
          <button className="lst-btn primary" onClick={() => void handleCreate()} disabled={creating || !asin.trim()}>
            {creating ? <Loader2 size={12} className="spin" /> : <Plus size={12} />} 新建
          </button>
        </div>
        {projects.length > 4 && (
          <label className="lst-rail-search">
            <Search size={11} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索项目…" />
          </label>
        )}
        <div className="listing-project-list lst-rail-list">
          {projects.length === 0 && (
            <div className="lst-rail-empty">暂无项目。输入 ASIN 新建，或先手动填写产品信息也可以开始。</div>
          )}
          {filtered.map((p) => {
            const running = p.active_jobs?.[0];
            return (
              <div key={p.id}
                className={`lst-project-card${activeId === p.id ? " active" : ""}`}
                onClick={() => onSelect(p.id)}>
                <div className="lst-project-top">
                  <strong>{p.asin}</strong>
                  {running ? (
                    <span className="lst-project-running"><Loader2 size={10} className="spin" />{JOB_LABEL[running] || "运行中"}</span>
                  ) : (
                    <span className={`lst-status-dot s-${p.status}`} title={STATUS_LABEL[p.status] || p.status} />
                  )}
                </div>
                {p.title && <div className="lst-project-title">{p.title}</div>}
                <div className="lst-project-meta">
                  <span>{p.marketplace}</span>
                  <span>·</span>
                  <span>{relativeTime(p.updated_at)}</span>
                  <button
                    className="lst-project-del"
                    title="删除项目"
                    onClick={async (e) => {
                      e.stopPropagation();
                      if (await confirm({ title: "删除项目", message: `确定删除 ${p.asin}？已生成的文案与图片配置将一并删除。`, confirmText: "删除", danger: true })) {
                        await onDelete(p.id);
                      }
                    }}>
                    <Trash2 size={11} />
                  </button>
                </div>
              </div>
            );
          })}
          {projects.length > 0 && filtered.length === 0 && (
            <div className="lst-rail-empty">没有匹配「{query}」的项目</div>
          )}
        </div>
      </div>
    </div>
  );
}
