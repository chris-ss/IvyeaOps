/**
 * Placeholder pages for the other Skill Studio tabs. Real implementations
 * land in phase D (browse/editor) and phase E (snapshots, trash, settings).
 */
export function SkillBrowsePlaceholder() {
  return (
    <div className="card" style={{ minHeight: 240 }}>
      <div className="ct">技能列表</div>
      <div style={{ color: "var(--t3)", fontSize: 11, padding: "32px 0", textAlign: "center" }}>
        阶段 D 将在此呈现 Skill 列表 + 编辑器。
        <br />
        当前后端 API 已就绪：<code>GET /api/skill/list</code>、<code>/item/{"{name}"}</code>、<code>/file/{"{name}"}</code>。
      </div>
    </div>
  );
}

export function TrashPlaceholder() {
  return (
    <div className="card" style={{ minHeight: 240 }}>
      <div className="ct">回收站（7 天 TTL）</div>
      <div style={{ color: "var(--t3)", fontSize: 11, padding: "32px 0", textAlign: "center" }}>
        阶段 E 会接入：删除的 skill 自动进入此处，点击恢复或永久清除。
      </div>
    </div>
  );
}

export function SettingsPlaceholder() {
  return (
    <div className="card" style={{ minHeight: 240 }}>
      <div className="ct">Studio 设置</div>
      <div style={{ color: "var(--t3)", fontSize: 11, padding: "32px 0", textAlign: "center" }}>
        阶段 E 会接入：快照保留数、回收站 TTL、自动保存节流、主题。
      </div>
    </div>
  );
}
