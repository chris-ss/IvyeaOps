import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject, RefObject } from "react";
import "xterm/css/xterm.css";
import { sendSocketMessage, stripAutoReplies } from "./shellUtils";

// xterm Terminal / FitAddon dynamic-import types — we don't bring in the
// type packages because they're tied to specific xterm versions. The
// `any` for now is intentional and isolated to this hook.
type XtermTerminal = any;
type XtermFitAddon = any;

type Options = {
  containerRef: RefObject<HTMLDivElement>;
  wsRef: MutableRefObject<WebSocket | null>;
  /** When true, terminal input is suppressed (used for native-selection mode). */
  inputBlocked?: boolean;
};

type Result = {
  terminalRef: MutableRefObject<XtermTerminal | null>;
  isReady: boolean;
  clear: () => void;
  fitNow: () => void;
  /** Re-emit current dimensions so the backend matches what we render. */
  resync: () => void;
};

const INIT_DELAY_MS = 120;
const RESIZE_DEBOUNCE_MS = 80;

/**
 * Owns the xterm.js Terminal instance + addons + DOM event handlers.
 *
 * Lifecycle is tied to the parent <div ref={containerRef} />; on first mount
 * we construct the terminal, install scrollback wheel/touch handlers, and
 * forward keystrokes into the WS. On unmount we tear everything down
 * cleanly (addon dispose, listeners, observer, terminal dispose).
 *
 * Patterns lifted from siteboon/claudecodeui useShellTerminal:
 *   - WebGL renderer with canvas fallback (perceptibly snappier on long output)
 *   - Custom wheel handler that drives scrollLines() rather than letting the
 *     browser scroll the surrounding flex container
 *   - Touch handlers for mobile scrollback
 *   - attachCustomKeyEventHandler for Ctrl+C-copy / Ctrl+V-paste interop
 */
export function useShellTerminal({ containerRef, wsRef, inputBlocked }: Options): Result {
  const termRef = useRef<XtermTerminal | null>(null);
  const fitRef = useRef<XtermFitAddon | null>(null);
  const resizeTimerRef = useRef<number | null>(null);
  const inputBlockedRef = useRef<boolean>(!!inputBlocked);
  inputBlockedRef.current = !!inputBlocked;
  const [isReady, setIsReady] = useState(false);

  const clear = useCallback(() => {
    const t = termRef.current;
    if (!t) return;
    t.clear();
    t.write("\x1b[2J\x1b[H");
  }, []);

  const fitNow = useCallback(() => {
    const fit = fitRef.current;
    if (!fit) return;
    try { fit.fit(); } catch { /* ignore — element may be detached */ }
  }, []);

  const resync = useCallback(() => {
    fitNow();
    const t = termRef.current;
    const ws = wsRef.current;
    if (!t) return;
    sendSocketMessage(ws, { type: "resize", cols: t.cols, rows: t.rows });
  }, [fitNow, wsRef]);

  // Main lifecycle — single-shot init on container mount.
  useEffect(() => {
    let disposed = false;
    const host = containerRef.current;
    if (!host) return;

    (async () => {
      const xterm = await import("xterm");
      const fitAddon = await import("xterm-addon-fit");
      if (disposed || !containerRef.current) return;

      const term: XtermTerminal = new xterm.Terminal({
        fontFamily: "'JetBrains Mono','Fira Code','SF Mono',Menlo,Consolas,monospace",
        fontSize: 12,
        lineHeight: 1.15,
        theme: {
          background: "#000000",
          foreground: "#e8e8e8",
          cursor: "#4ade80",
          selectionBackground: "rgba(74,222,128,.25)",
        },
        cursorBlink: true,
        scrollback: 5000,
        convertEol: false,
        allowTransparency: false,
      });
      const fit: XtermFitAddon = new fitAddon.FitAddon();
      term.loadAddon(fit);

      // Try WebGL — much smoother on busy output (claude/codex spam).
      try {
        const webgl = await import("xterm-addon-webgl");
        term.loadAddon(new webgl.WebglAddon());
      } catch {
        // Canvas fallback (default). No-op when webgl addon isn't installed.
      }

      term.open(containerRef.current);
      termRef.current = term;
      fitRef.current = fit;

      // Forward keystrokes to the server, swallowing OSC color replies the
      // emulator itself sometimes echoes.
      const dataSub = term.onData((data: string) => {
        if (inputBlockedRef.current) return;
        const cleaned = stripAutoReplies(data);
        if (!cleaned) return;
        sendSocketMessage(wsRef.current, { type: "input", data: cleaned });
      });

      // Wheel: scroll xterm's scrollback instead of the page.
      const getRowHeight = () => {
        const fs = typeof term.options.fontSize === "number" ? term.options.fontSize : 12;
        const lh = typeof term.options.lineHeight === "number" ? term.options.lineHeight : 1.15;
        return Math.max(1, fs * lh);
      };
      const canScroll = (lines: number) => {
        if (lines === 0 || term.buffer.active.type !== "normal") return false;
        const { viewportY, baseY } = term.buffer.active;
        return lines < 0 ? viewportY > 0 : viewportY < baseY;
      };
      let wheelFrac = 0;
      const onWheel = (e: WheelEvent) => {
        if (e.deltaY === 0 || e.shiftKey) return;
        let lines = e.deltaY;
        if (e.deltaMode === WheelEvent.DOM_DELTA_PIXEL) lines = e.deltaY / getRowHeight();
        else if (e.deltaMode === WheelEvent.DOM_DELTA_PAGE) lines = e.deltaY * term.rows;
        wheelFrac += lines;
        const whole = wheelFrac > 0 ? Math.floor(wheelFrac) : Math.ceil(wheelFrac);
        if (whole === 0) {
          if (canScroll(wheelFrac)) { e.preventDefault(); e.stopPropagation(); }
          return;
        }
        wheelFrac -= whole;
        if (canScroll(whole)) {
          term.scrollLines(whole);
          e.preventDefault();
          e.stopPropagation();
        } else {
          wheelFrac = 0;
        }
      };

      // Touch: 1-finger drag = scrollback on mobile.
      let touchY: number | null = null;
      let touchFrac = 0;
      const onTouchStart = (e: TouchEvent) => {
        if (e.touches.length !== 1) { touchY = null; touchFrac = 0; return; }
        touchY = e.touches[0].pageY;
      };
      const onTouchMove = (e: TouchEvent) => {
        if (e.touches.length !== 1 || touchY === null) return;
        const next = e.touches[0].pageY;
        const dy = touchY - next;
        touchY = next;
        if (dy === 0) return;
        touchFrac += dy / getRowHeight();
        const whole = touchFrac > 0 ? Math.floor(touchFrac) : Math.ceil(touchFrac);
        if (whole === 0) {
          if (canScroll(touchFrac)) { e.preventDefault(); e.stopPropagation(); }
          return;
        }
        touchFrac -= whole;
        if (canScroll(whole)) {
          term.scrollLines(whole);
          e.preventDefault();
          e.stopPropagation();
        } else {
          touchFrac = 0;
        }
      };
      const onTouchEnd = () => { touchY = null; touchFrac = 0; };

      const el: HTMLElement | undefined = term.element;
      el?.addEventListener("wheel", onWheel, { capture: true, passive: false });
      el?.addEventListener("touchstart", onTouchStart, { capture: true, passive: true });
      el?.addEventListener("touchmove", onTouchMove, { capture: true, passive: false });
      el?.addEventListener("touchend", onTouchEnd, { capture: true, passive: true });
      el?.addEventListener("touchcancel", onTouchEnd, { capture: true, passive: true });

      // Native Ctrl+C copy / Ctrl+V paste so the user doesn't have to think
      // about them. Without this, xterm swallows them as terminal input.
      term.attachCustomKeyEventHandler((event: KeyboardEvent) => {
        if (event.type === "keydown" && (event.ctrlKey || event.metaKey)
            && event.key?.toLowerCase() === "c" && term.hasSelection()) {
          event.preventDefault();
          event.stopPropagation();
          const sel = term.getSelection();
          if (sel && navigator.clipboard?.writeText) {
            navigator.clipboard.writeText(sel).catch(() => {});
          }
          return false;
        }
        if (event.type === "keydown" && (event.ctrlKey || event.metaKey)
            && event.key?.toLowerCase() === "v") {
          event.preventDefault();
          event.stopPropagation();
          if (navigator.clipboard?.readText) {
            navigator.clipboard.readText()
              .then(text => sendSocketMessage(wsRef.current, { type: "input", data: text }))
              .catch(() => {});
          }
          return false;
        }
        return true;
      });

      // First fit + size handshake to server.
      window.setTimeout(() => {
        fit.fit();
        sendSocketMessage(wsRef.current, { type: "resize", cols: term.cols, rows: term.rows });
        setIsReady(true);
      }, INIT_DELAY_MS);

      // Re-fit on container resize (panel toggle, window resize, mobile rotation).
      const ro = new ResizeObserver(() => {
        if (resizeTimerRef.current) window.clearTimeout(resizeTimerRef.current);
        resizeTimerRef.current = window.setTimeout(() => {
          fit.fit();
          sendSocketMessage(wsRef.current, { type: "resize", cols: term.cols, rows: term.rows });
        }, RESIZE_DEBOUNCE_MS);
      });
      ro.observe(containerRef.current);

      // Stash cleanup on the terminal so the outer disposer can grab it.
      (term as any)._opshubCleanup = () => {
        el?.removeEventListener("wheel", onWheel, { capture: true } as any);
        el?.removeEventListener("touchstart", onTouchStart, { capture: true } as any);
        el?.removeEventListener("touchmove", onTouchMove, { capture: true } as any);
        el?.removeEventListener("touchend", onTouchEnd, { capture: true } as any);
        el?.removeEventListener("touchcancel", onTouchEnd, { capture: true } as any);
        ro.disconnect();
        dataSub.dispose();
        if (resizeTimerRef.current) {
          window.clearTimeout(resizeTimerRef.current);
          resizeTimerRef.current = null;
        }
      };
    })();

    return () => {
      disposed = true;
      const term = termRef.current;
      if (term) {
        try { (term as any)._opshubCleanup?.(); } catch { /* ignore */ }
        try { term.dispose(); } catch { /* ignore */ }
        termRef.current = null;
      }
      fitRef.current = null;
      setIsReady(false);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { terminalRef: termRef, isReady, clear, fitNow, resync };
}
