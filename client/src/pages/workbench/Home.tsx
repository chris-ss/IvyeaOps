import { Link } from "react-router-dom";

/**
 * Home landing page — high-signal overview, no AI chat (that lives under /ai).
 * Today's metrics are still mock; they'll become real once a data source
 * (Hermes pipeline / SP-API) is wired up.
 */
export default function Home() {
  return (
    <div>
      <div className="ptitle">/ 今日概览</div>

      <div className="g4 mb10">
        <Metric label="广告花费" value="$48.2" hint="↑ 12% vs 昨日" hintKind="up" />
        <Metric label="订单数" value="31" hint="↑ 7 vs 昨日" hintKind="up" />
        <Metric label="ACoS" value="18.4%" hint="↓ 2.1%" hintKind="dn" />
        <Metric label="库存剩余" value="214" hint="约 32 天" hintKind="neu" />
      </div>

      <div className="g4 mb14">
        <Metric
          label="Agent 任务"
          value={<span style={{ color: "var(--acc)" }}>3</span>}
          hint="运行中"
          hintKind="neu"
        />
        <Metric
          label="服务器负载"
          value={<span style={{ color: "var(--amber)" }}>—</span>}
          hint="见监控页"
          hintKind="neu"
        />
        <Metric label="Skill 数量" value="12" hint="活跃技能" hintKind="neu" />
        <Metric
          label="VPN 状态"
          value={
            <span style={{ color: "var(--acc)", fontSize: 13 }}>● ONLINE</span>
          }
          hint="VLESS + CF CDN"
          hintKind="neu"
        />
      </div>

      <div className="sl">快捷入口</div>
      <div className="g4 mb14">
        <ShortcutCard
          to="/dashboard"
          title="Hermes 仪表盘"
          line1={<span style={{ color: "var(--acc)" }}>数据 Pipeline</span>}
          line2="关键词 / 广告 / 竞品"
          icon="▦"
        />
        <ShortcutCard
          to="/ai"
          title="AI 助手"
          line1={<span style={{ color: "var(--blue)" }}>Claude Code UI</span>}
          line2="对话 / 代码 / 任务"
          icon="◈"
        />
        <ShortcutCard
          to="/terminal"
          title="服务器终端"
          line1={<span style={{ color: "var(--acc)" }}>Web Shell</span>}
          line2="170.106.83.241"
          icon="▶"
        />
        <ShortcutCard
          to="/servmon"
          title="服务器监控"
          line1={<span style={{ color: "var(--amber)" }}>实时指标</span>}
          line2="CPU / RAM / 网络"
          icon="◉"
        />
        <ShortcutCard
          to="/tools"
          title="工具箱"
          line1={<span style={{ color: "var(--purple)" }}>日常小工具</span>}
          line2="ASIN / Prompt / 模板"
          icon="⚙"
        />
        <ShortcutCard
          to="/skill"
          title="Skill Studio"
          line1={<span style={{ color: "var(--cyan)" }}>桌面版</span>}
          line2="Skill 资产管理"
          icon="✦"
        />
        <ShortcutCard
          to="/news"
          title="资讯"
          line1={<span style={{ color: "var(--t2)" }}>3 条未读</span>}
          line2="政策 / 广告 / AI"
          icon="≡"
        />
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  hintKind,
}: {
  label: string;
  value: React.ReactNode;
  hint: string;
  hintKind: "up" | "dn" | "neu";
}) {
  return (
    <div className="met">
      <div className="ml">{label}</div>
      <div className="mv">{value}</div>
      <div className={"ms " + hintKind}>{hint}</div>
    </div>
  );
}

function ShortcutCard({
  to,
  title,
  line1,
  line2,
  icon,
}: {
  to: string;
  title: string;
  line1: React.ReactNode;
  line2: string;
  icon: string;
}) {
  return (
    <Link to={to} style={{ textDecoration: "none" }}>
      <div className="card" style={{ cursor: "pointer" }}>
        <div className="ct" style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ color: "var(--acc)" }}>{icon}</span> {title}
        </div>
        <div style={{ fontSize: 10 }}>{line1}</div>
        <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 3 }}>{line2}</div>
      </div>
    </Link>
  );
}
