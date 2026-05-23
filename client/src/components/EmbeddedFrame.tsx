import { useEffect, useRef, useState, ReactNode } from "react";

// If the iframe doesn't fire onLoad within this window, we flip to "fail".
// Covers the case where the upstream hangs or the browser silently drops the
// response (X-Frame-Options, network stall, 502 without body, etc.) — onError
// isn't fired cross-origin, so a timer is the only reliable signal.
const LOAD_TIMEOUT_MS = 10_000;

/**
 * Wrapper for iframe-embedded external tools.
 *
 * Targets typically live on cross-subdomain hosts (e.g. cli/hermes/term.*),
 * so we can't reliably HEAD-probe them from the parent origin (CORS). Instead
 * we just render the iframe directly and let onLoad/onError/timeout signal state.
 */
export default function EmbeddedFrame({
  title,
  src,
  fallback,
}: {
  title: string;
  src: string;
  fallback: ReactNode;
}) {
  const [state, setState] = useState<"loading" | "ok" | "fail">("loading");
  // Force-reload on retry via key bump.
  const [reloadKey, setReloadKey] = useState(0);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    setState("loading");
    if (timerRef.current) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      // setState is a no-op if we've already transitioned to "ok"/"fail"
      // because the timer would have been cleared in onLoad. This path only
      // fires when the iframe is genuinely stuck.
      setState((prev) => (prev === "loading" ? "fail" : prev));
    }, LOAD_TIMEOUT_MS);
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, [reloadKey, src]);

  const clearTimer = () => {
    if (timerRef.current) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  return (
    <div style={{ height: "calc(100vh - 72px)", display: "flex", flexDirection: "column" }}>
      <div
        className="ptitle"
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}
      >
        <span>/ {title}</span>
        <span
          style={{
            fontSize: 9,
            color: "var(--t3)",
            textTransform: "none",
            letterSpacing: 0,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          {state === "loading" && (
            <>
              <span className="spin" /> 加载中
            </>
          )}
          {state === "ok" && <span style={{ color: "var(--acc)" }}>● 已加载</span>}
          {state === "fail" && <span style={{ color: "var(--amber)" }}>⚠ 加载失败</span>}
          <a
            href={src}
            target="_blank"
            rel="noreferrer"
            style={{ color: "var(--blue)", textDecoration: "none" }}
          >
            ↗ 新窗口
          </a>
        </span>
      </div>

      {state === "fail" ? (
        <div
          className="card"
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
          }}
        >
          <div style={{ maxWidth: 480, fontSize: 11, color: "var(--t2)", lineHeight: 1.8 }}>
            <div
              style={{
                fontSize: 28,
                color: "var(--amber)",
                marginBottom: 10,
                fontFamily: "var(--font)",
              }}
            >
              ⚠
            </div>
            <div style={{ marginBottom: 12, fontSize: 12, color: "var(--t)" }}>
              无法加载 <code>{src}</code>
            </div>
            <div style={{ fontSize: 10, color: "var(--t3)" }}>{fallback}</div>
            <button
              className="tbtn"
              style={{ marginTop: 14 }}
              onClick={() => setReloadKey((k) => k + 1)}
            >
              ↻ 重试
            </button>
          </div>
        </div>
      ) : (
        <iframe
          key={reloadKey}
          title={title}
          src={src}
          onLoad={() => {
            clearTimer();
            setState("ok");
          }}
          onError={() => {
            clearTimer();
            setState("fail");
          }}
          style={{
            flex: 1,
            width: "100%",
            border: "1px solid var(--b)",
            borderRadius: "var(--r)",
            background: "var(--bg2)",
            opacity: state === "loading" ? 0.3 : 1,
            transition: "opacity .3s",
          }}
        />
      )}
    </div>
  );
}
