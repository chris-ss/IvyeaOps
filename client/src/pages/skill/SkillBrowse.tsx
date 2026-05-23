import { useCallback, useEffect, useMemo, useState, lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { listSkills, SkillMeta } from "../../api/skill";

// SkillEditor brings in CodeMirror (~240KB gzip) — keep it off the list page.
const SkillEditor = lazy(() => import("./SkillEditor"));

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

export default function SkillBrowse() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const category = params.get("category") ?? "";
  const selected = params.get("name") ?? "";

  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Bumped whenever a mutation (delete, create) should refetch the list.
  const [refreshKey, setRefreshKey] = useState(0);

  // Local debounce for the search input so we don't thrash the URL bar / API.
  const [qInput, setQInput] = useState(q);
  useEffect(() => setQInput(q), [q]);
  useEffect(() => {
    if (qInput === q) return;
    const t = setTimeout(() => {
      const next = new URLSearchParams(params);
      if (qInput) next.set("q", qInput);
      else next.delete("q");
      setParams(next, { replace: true });
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qInput]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setErr(null);
    listSkills({ q: q || undefined, category: category || undefined })
      .then((r) => { if (alive) setSkills(r.skills); })
      .catch((e) => { if (alive) setErr(e?.response?.data?.detail ?? e.message ?? "加载失败"); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [q, category, refreshKey]);

  const categories = useMemo(() => {
    const seen = new Set<string>();
    skills.forEach((s) => s.category && seen.add(s.category));
    return Array.from(seen).sort();
  }, [skills]);

  const pickSkill = (name: string) => {
    const next = new URLSearchParams(params);
    next.set("name", name);
    setParams(next, { replace: true });
  };

  const clearSelection = () => {
    const next = new URLSearchParams(params);
    next.delete("name");
    setParams(next, { replace: true });
  };

  return (
    <div className="sks-browse">
      {/* Toolbar */}
      <div className="sks-list-toolbar">
        <input
          className="sks-input"
          placeholder="搜索 name / description…"
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
        />
        <select
          className="sks-input"
          style={{ flex: "0 0 auto", minWidth: 140 }}
          value={category}
          onChange={(e) => {
            const next = new URLSearchParams(params);
            if (e.target.value) next.set("category", e.target.value);
            else next.delete("category");
            setParams(next, { replace: true });
          }}
        >
          <option value="">全部分类</option>
          {categories.map((c) => (
            <option key={c} value={c}>{c || "(顶层)"}</option>
          ))}
        </select>
        <span style={{ color: "var(--t3)", fontSize: 10, marginLeft: "auto" }}>
          {loading ? "加载中…" : `共 ${skills.length} 项`}
        </span>
      </div>

      {err && <div className="sks-error">⚠ {err}</div>}

      {/* Two-column layout: list + detail */}
      <div className={"sks-browse-split" + (selected ? " has-sel" : "")}>
        <div className="sks-list">
          {!loading && skills.length === 0 ? (
            <div className="sks-empty">没有符合条件的 skill</div>
          ) : (
            skills.map((s) => (
              <div
                key={s.name}
                className={"sks-list-row" + (s.name === selected ? " active" : "")}
                onClick={() => pickSkill(s.name)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && pickSkill(s.name)}
              >
                <div>
                  <div className="title">
                    {s.name}
                    {s.pinned && <span className="sks-badge">PINNED</span>}
                  </div>
                  {(s.description_zh || s.description) && (
                    <div className="desc">{s.description_zh || s.description}</div>
                  )}
                </div>
                <div className="cat">{s.category || "-"}</div>
                <div className="date">{fmtDate(s.updated_at)}</div>
              </div>
            ))
          )}
        </div>

        {selected && (
          <Suspense fallback={<aside className="sks-detail"><div className="sks-loading">编辑器加载中…</div></aside>}>
            <SkillEditor
              name={selected}
              onClose={clearSelection}
              onDeleted={() => setRefreshKey((k) => k + 1)}
            />
          </Suspense>
        )}
      </div>
    </div>
  );
}
