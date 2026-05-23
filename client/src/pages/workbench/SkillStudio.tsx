import { useState } from "react";
import EmbeddedFrame from "../../components/EmbeddedFrame";

/**
 * skill-studio is a Tauri desktop app, but its React front-end detects when
 * it's running outside a Tauri shell and falls back to in-memory mock state
 * (see its browserPreviewMocks.ts). So we serve the pre-built `dist/`
 * from nginx at /skill-studio/ and simply iframe it.
 *
 * Local filesystem I/O, snapshots backed by disk, and update checks don't
 * work in this mode — users who need the real thing should grab the desktop
 * build from GitHub Releases (banner below).
 */
export default function SkillStudio() {
  const [showNote, setShowNote] = useState(true);

  return (
    <div style={{ height: "calc(100vh - 72px)", display: "flex", flexDirection: "column" }}>
      {showNote && (
        <div
          style={{
            background: "rgba(96,165,250,.06)",
            border: "1px solid rgba(96,165,250,.25)",
            borderRadius: "var(--r)",
            padding: "7px 12px",
            marginBottom: 8,
            fontSize: 10,
            color: "var(--t2)",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <span style={{ color: "var(--blue)" }}>ℹ</span>
          <span style={{ flex: 1 }}>
            浏览器预览模式：Skill / Snapshot 数据为内存 mock，完整功能（本地文件系统、团队同步、离线快照）请使用桌面版。
          </span>
          <a
            href="https://github.com/liu673/skill-studio/releases"
            target="_blank"
            rel="noreferrer"
            className="tbtn"
            style={{
              textDecoration: "none",
              fontSize: 10,
              color: "var(--blue)",
              borderColor: "rgba(96,165,250,.3)",
            }}
          >
            ↓ 下载桌面版
          </a>
          <button
            className="tbtn"
            style={{ fontSize: 10 }}
            onClick={() => setShowNote(false)}
          >
            ✕
          </button>
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0 }}>
        <EmbeddedFrame
          title="Skill Studio"
          src="/skill-studio/"
          fallback={
            <>
              skill-studio 静态资源不可访问。预期 nginx 在{" "}
              <code>/skill-studio/</code> 服务 <code>/root/skill-studio/dist/</code>。
              <br />
              构建：<code>cd /root/skill-studio && npm run build</code>
            </>
          }
        />
      </div>
    </div>
  );
}
