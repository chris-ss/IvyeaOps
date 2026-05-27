import { lazy, Suspense, useState } from "react";
import SkillTools from "./SkillTools";
import IdeaSkill from "./IdeaSkill";
import SkillManage from "./skill/SkillManage";

const ImportGitHubDialog = lazy(() => import("../skill/ImportGitHubDialog"));

const TABS = [
  { key: "tools", label: "工具" },
  { key: "create", label: "创建" },
  { key: "manage", label: "管理" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function SkillHub() {
  const [tab, setTab] = useState<TabKey>("tools");
  const [showGithubImport, setShowGithubImport] = useState(false);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <div className="ptitle" style={{ marginBottom: 0 }}>/ Skill 中心</div>
        <div style={{ display: "flex", gap: 2 }}>
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                padding: "5px 14px",
                fontSize: 11,
                border: "none",
                borderRadius: 3,
                cursor: "pointer",
                background: tab === t.key ? "var(--acc)" : "var(--bg2)",
                color: tab === t.key ? "#000" : "var(--t2)",
                fontWeight: tab === t.key ? 600 : 400,
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === "tools" && <div className="skill-hub-tab"><SkillTools /></div>}
      {tab === "create" && <div className="skill-hub-tab"><IdeaSkill /></div>}
      {tab === "manage" && (
        <div>
          <div style={{ marginBottom: 10, display: "flex", gap: 8 }}>
            <button
              className="tbtn"
              onClick={() => setShowGithubImport(true)}
              style={{ fontSize: 10 }}
            >
              ⬇ 从 GitHub 导入 Skill
            </button>
          </div>
          <SkillManage />
        </div>
      )}

      {showGithubImport && (
        <Suspense fallback={null}>
          <ImportGitHubDialog onClose={() => setShowGithubImport(false)} />
        </Suspense>
      )}
    </div>
  );
}
