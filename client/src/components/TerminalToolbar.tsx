import { useEffect, useMemo, useRef, useState, RefObject } from "react";

/**
 * Mobile-only toolbar rendered in the ops-hub parent page, BELOW the
 * ttyd iframe. Keys are forwarded to the iframe via postMessage so they
 * don't consume terminal screen real estate inside the iframe.
 *
 * iframe-side bridge: /var/www/term-toolbar/boot.js (sub_filter-injected).
 * The `iframeOrigin` prop must match the iframe's `src` origin so postMessage
 * targetOrigin and the inbound `e.origin` check both work.
 */

type Msg =
  | { type: "key"; bytes: string }
  | { type: "select-mode"; on: boolean }
  | { type: "ping" };

type IncomingMsg =
  | { type: "ready" }
  | { type: "ws-closed" }
  | { type: "bridge-loaded" };

function isTouchViewport(): boolean {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia("(pointer: coarse)").matches ||
    window.matchMedia("(max-width: 768px)").matches
  );
}

function originOf(url: string): string {
  try {
    return new URL(url).origin;
  } catch {
    return "";
  }
}

export default function TerminalToolbar({
  iframeRef,
  iframeUrl,
}: {
  iframeRef: RefObject<HTMLIFrameElement>;
  iframeUrl: string;
}) {
  const IFRAME_ORIGIN = useMemo(() => originOf(iframeUrl), [iframeUrl]);
  const [visible, setVisible] = useState<boolean>(() => isTouchViewport());
  const [wsReady, setWsReady] = useState(false);
  const [stickyCtrl, setStickyCtrl] = useState(false);
  const [stickyAlt, setStickyAlt] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const ctrlRef = useRef(stickyCtrl);
  const altRef = useRef(stickyAlt);
  ctrlRef.current = stickyCtrl;
  altRef.current = stickyAlt;

  // React to viewport changes (e.g. rotation, split-screen).
  useEffect(() => {
    const mq1 = window.matchMedia("(pointer: coarse)");
    const mq2 = window.matchMedia("(max-width: 768px)");
    const sync = () => setVisible(isTouchViewport());
    mq1.addEventListener("change", sync);
    mq2.addEventListener("change", sync);
    return () => {
      mq1.removeEventListener("change", sync);
      mq2.removeEventListener("change", sync);
    };
  }, []);

  // Receive bridge status messages from the iframe.
  useEffect(() => {
    function onMsg(e: MessageEvent) {
      if (e.origin !== IFRAME_ORIGIN) return;
      const msg = e.data as IncomingMsg | null;
      if (!msg || typeof msg !== "object") return;
      if (msg.type === "ready") setWsReady(true);
      else if (msg.type === "ws-closed") setWsReady(false);
      else if (msg.type === "bridge-loaded") {
        // Re-enter selection mode if the user had it on and the iframe reloaded.
        post({ type: "select-mode", on: selectMode });
      }
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [selectMode]);

  function post(msg: Msg) {
    const win = iframeRef.current?.contentWindow;
    if (!win) return;
    try {
      win.postMessage(msg, IFRAME_ORIGIN);
    } catch {
      /* ignored */
    }
  }

  function sendBytesRaw(bytes: string) {
    let payload = bytes;
    if (ctrlRef.current && bytes.length === 1 && /[a-zA-Z]/.test(bytes)) {
      payload = String.fromCharCode(bytes.toLowerCase().charCodeAt(0) - 96);
      setStickyCtrl(false);
    }
    if (altRef.current) {
      payload = "\x1b" + payload;
      setStickyAlt(false);
    }
    post({ type: "key", bytes: payload });
  }

  function sendKey(bytes: string) {
    sendBytesRaw(bytes);
  }

  function sendCtrlLetter(letter: string) {
    const code = letter.toLowerCase().charCodeAt(0) - 96;
    post({ type: "key", bytes: String.fromCharCode(code) });
  }

  async function doPaste() {
    try {
      const text = await navigator.clipboard.readText();
      if (text) post({ type: "key", bytes: text });
    } catch {
      alert("浏览器拒绝了剪贴板读取权限");
    }
  }

  function toggleSelectMode() {
    const next = !selectMode;
    setSelectMode(next);
    post({ type: "select-mode", on: next });
  }

  if (!visible) return null;

  const keyBtn = (label: string, onClick: () => void, active = false) => (
    <button
      type="button"
      className={"tt-key" + (active ? " tt-active" : "")}
      onMouseDown={(e) => e.preventDefault()}
      onTouchStart={(e) => e.preventDefault()}
      onClick={(e) => {
        e.preventDefault();
        onClick();
      }}
      disabled={!wsReady && label !== "✕"}
    >
      {label}
    </button>
  );

  return (
    <div className="tt-bar" data-ws-ready={wsReady ? "1" : "0"}>
      <div className="tt-row">
        {keyBtn("Esc", () => sendKey("\x1b"))}
        {keyBtn("Tab", () => sendKey("\t"))}
        {keyBtn("Ctrl", () => setStickyCtrl((v) => !v), stickyCtrl)}
        {keyBtn("Alt", () => setStickyAlt((v) => !v), stickyAlt)}
        {keyBtn("←", () => sendKey("\x1b[D"))}
        {keyBtn("↓", () => sendKey("\x1b[B"))}
        {keyBtn("↑", () => sendKey("\x1b[A"))}
        {keyBtn("→", () => sendKey("\x1b[C"))}
      </div>
      <div className="tt-row">
        {keyBtn("^C", () => sendCtrlLetter("c"))}
        {keyBtn("^D", () => sendCtrlLetter("d"))}
        {keyBtn("^Z", () => sendCtrlLetter("z"))}
        {keyBtn("^L", () => sendCtrlLetter("l"))}
        {keyBtn("^R", () => sendCtrlLetter("r"))}
        {keyBtn("📋", () => doPaste())}
        {keyBtn("🔍", toggleSelectMode, selectMode)}
        {keyBtn("✕", () => setVisible(false))}
      </div>
      <style>{`
        .tt-bar{
          display:flex;flex-direction:column;gap:3px;
          padding:4px;
          background:var(--bg1);border-bottom:1px solid var(--b);
          flex-shrink:0;
        }
        .tt-row{display:flex;gap:3px;width:100%}
        .tt-key{
          flex:1 1 0;min-width:0;height:34px;padding:0 2px;
          border:1px solid var(--b);border-radius:var(--r);
          background:var(--bg2);color:var(--t);
          font-family:var(--font);font-size:13px;font-weight:500;
          cursor:pointer;white-space:nowrap;overflow:hidden;
          -webkit-tap-highlight-color:transparent;
          touch-action:manipulation;
        }
        .tt-key:active{background:var(--bg3)}
        .tt-key:disabled{opacity:.35;cursor:not-allowed}
        .tt-key.tt-active{
          background:var(--blue);border-color:var(--blue);color:#fff;
        }
      `}</style>
    </div>
  );
}
