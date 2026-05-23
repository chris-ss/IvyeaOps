import { useEffect, useState } from "react";
import EmbeddedFrame from "../../components/EmbeddedFrame";
import { getSettings } from "../../api/settings";

export default function Dashboard() {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    getSettings()
      .then((r) => setSrc(r.settings.dashboard_url || ""))
      .catch(() => setSrc(""));
  }, []);
  if (src === null) return <div style={{ padding: 24, color: "var(--t3)" }}>加载配置中…</div>;
  if (!src) return (
    <div className="card" style={{ margin: 24, padding: 24, color: "var(--t2)" }}>
      仪表盘地址未配置。请前往 <code>系统配置 → 内嵌服务地址</code> 设置 dashboard_url。
    </div>
  );
  return (
    <EmbeddedFrame
      title="Dashboard"
      src={src}
      fallback={
        <>
          Dashboard 服务未响应。检查目标地址 <code>{src}</code> 是否在线。
        </>
      }
    />
  );
}
