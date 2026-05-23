/*
 * ttyd iframe-side bridge for the ops-hub terminal toolbar.
 *
 * Runs inside the ttyd iframe. The mobile toolbar UI lives in the parent
 * page (ops-hub); this script only:
 *   1. Captures the ttyd WebSocket to send raw bytes to the pty
 *   2. Listens for postMessage from the parent to dispatch keys
 *   3. Adds a capture-phase scroll fallback for xterm scrollback
 *   4. Provides a capture-phase touch blocker for "selection mode" so
 *      mobile browsers can use long-press → system copy menu on xterm.js
 *
 * ttyd WebSocket frame format (client->server): '0' + bytes = INPUT to pty.
 *
 * Requires ttyd running with `-t rendererType=dom` so the glyphs are real
 * text nodes (canvas renderer can't be selected on mobile).
 */
(function () {
  'use strict';

  // Derive the ops-hub origin from the embedding referrer at load time so
  // the bridge works against any deployment hostname (not just ours). If
  // the iframe is opened standalone (no referrer) we fall back to '*',
  // which only relaxes outbound postMessage targeting; inbound messages
  // are still origin-checked so this is safe.
  var PARENT_ORIGIN = (function () {
    try {
      if (document.referrer) return new URL(document.referrer).origin;
    } catch (_) { /* fall through */ }
    return '*';
  })();
  var CAPTURED_WS = null;
  var OSC_COLOR_REPLY_RE = /\x1b\](10|11);(?:rgb:[0-9a-fA-F/]+|\?)(?:\x07|\x1b\\)/g;
  var BARE_OSC_COLOR_REPLY_RE = /\](10|11);rgb:[0-9a-fA-F/]+/g;

  function stripTerminalAutoReplies(bytes) {
    if (!bytes || typeof bytes !== 'string') return bytes;
    var next = bytes.replace(OSC_COLOR_REPLY_RE, '');
    // Some browser/xterm/transport combinations surface the color reply with
    // the leading ESC already consumed. Filter the visible fallback too.
    next = next.replace(BARE_OSC_COLOR_REPLY_RE, '');
    return next;
  }

  function sendRawBytes(bytes) {
    if (!CAPTURED_WS || CAPTURED_WS.readyState !== 1) return false;
    CAPTURED_WS.send('0' + bytes);
    return true;
  }

  // ---- 1. WebSocket interception ----
  var NativeWS = window.WebSocket;
  function HookedWS(url, protocols) {
    var ws = protocols !== undefined ? new NativeWS(url, protocols) : new NativeWS(url);
    try {
      if (/\/ws(\?|$)/.test(url) || (protocols && String(protocols).indexOf('tty') !== -1)) {
        var nativeSend = ws.send.bind(ws);
        ws.send = function (data) {
          if (typeof data === 'string' && data.charAt(0) === '0') {
            var filtered = stripTerminalAutoReplies(data.slice(1));
            if (!filtered) return;
            return nativeSend('0' + filtered);
          }
          return nativeSend(data);
        };
        ws.addEventListener('open', function () {
          CAPTURED_WS = ws;
          postToParent({ type: 'ready' });
        });
        ws.addEventListener('close', function () {
          if (CAPTURED_WS === ws) CAPTURED_WS = null;
          postToParent({ type: 'ws-closed' });
        });
      }
    } catch (_) {}
    return ws;
  }
  HookedWS.prototype = NativeWS.prototype;
  HookedWS.CONNECTING = NativeWS.CONNECTING;
  HookedWS.OPEN = NativeWS.OPEN;
  HookedWS.CLOSING = NativeWS.CLOSING;
  HookedWS.CLOSED = NativeWS.CLOSED;
  window.WebSocket = HookedWS;

  function sendBytes(bytes) {
    var filtered = stripTerminalAutoReplies(bytes);
    if (!filtered) return false;
    return sendRawBytes(filtered);
  }

  function postToParent(msg) {
    if (window.parent && window.parent !== window) {
      try { window.parent.postMessage(msg, PARENT_ORIGIN); } catch (_) {}
    }
  }

  // ---- 2. Scrollback fallback ----
  //
  // On mobile, ttyd/xterm can swallow touchmove events before native viewport
  // scrolling happens, especially inside a cross-origin iframe. Scroll the
  // xterm viewport directly so users can review previous terminal output.
  function findXtermViewport(target) {
    var el = target && target.nodeType === 1 ? target : target && target.parentElement;
    while (el && el !== document.body) {
      if (el.classList && el.classList.contains('xterm-viewport')) return el;
      if (el.classList && (el.classList.contains('xterm') || el.classList.contains('terminal'))) break;
      el = el.parentElement;
    }
    return document.querySelector('.xterm-viewport');
  }

  function canScrollViewport(viewport, deltaY) {
    if (!viewport || !deltaY) return false;
    var maxTop = viewport.scrollHeight - viewport.clientHeight;
    if (maxTop <= 0) return false;
    return deltaY < 0 ? viewport.scrollTop > 0 : viewport.scrollTop < maxTop;
  }

  function scrollViewport(viewport, deltaY, event) {
    if (!canScrollViewport(viewport, deltaY)) return false;
    viewport.scrollTop += deltaY;
    event.preventDefault();
    event.stopImmediatePropagation();
    return true;
  }

  var lastTouchY = null;
  function handleScrollTouchStart(e) {
    if (selectionMode || e.touches.length !== 1) {
      lastTouchY = null;
      return;
    }
    lastTouchY = e.touches[0].pageY;
  }

  function handleScrollTouchMove(e) {
    if (selectionMode || e.touches.length !== 1 || lastTouchY === null) return;
    var y = e.touches[0].pageY;
    var deltaY = lastTouchY - y;
    lastTouchY = y;
    var viewport = findXtermViewport(e.target);
    if (!viewport) return;
    if (!scrollViewport(viewport, deltaY, e)) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }

  function handleScrollTouchEnd() {
    lastTouchY = null;
  }

  function handleScrollWheel(e) {
    if (selectionMode || e.deltaY === 0 || e.shiftKey) return;
    var viewport = findXtermViewport(e.target);
    if (!viewport) return;
    var deltaY = e.deltaY;
    if (e.deltaMode === WheelEvent.DOM_DELTA_LINE) deltaY *= 16;
    else if (e.deltaMode === WheelEvent.DOM_DELTA_PAGE) deltaY *= window.innerHeight;
    if (!scrollViewport(viewport, deltaY, e)) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }

  document.addEventListener('touchstart', handleScrollTouchStart, { capture: true, passive: true });
  document.addEventListener('touchmove', handleScrollTouchMove, { capture: true, passive: false });
  document.addEventListener('touchend', handleScrollTouchEnd, { capture: true, passive: true });
  document.addEventListener('touchcancel', handleScrollTouchEnd, { capture: true, passive: true });
  document.addEventListener('wheel', handleScrollWheel, { capture: true, passive: false });

  // ---- 3. Selection mode ----
  //
  // Two layers block text selection on xterm.js mobile:
  //   (a) inline style `user-select: none` or CSS from xterm's own stylesheet
  //       — we override with inline `user-select: text` (highest CSS priority)
  //   (b) xterm attaches touchstart/touchmove/mousedown/selectstart handlers
  //       that call preventDefault — we stop them at document capture phase.
  var selectionMode = false;
  var XTERM_SELECTORS = [
    '.xterm', '.xterm-screen', '.xterm-viewport',
    '.xterm-rows', '.xterm-helpers', '.terminal',
    '.xterm-selection-layer', '.xterm-text-layer'
  ];
  var savedInlineStyles = []; // [{ el, prop, prev }]

  function forceInlineUserSelect(on) {
    if (on) {
      var seen = new Set();
      XTERM_SELECTORS.forEach(function (sel) {
        document.querySelectorAll(sel).forEach(function (el) {
          if (seen.has(el)) return;
          seen.add(el);
          // Save & override inline styles on this element and all descendants.
          applyInline(el);
          el.querySelectorAll('*').forEach(applyInline);
        });
      });
      // Body fallback so long-press anywhere has a chance.
      applyInline(document.body);
    } else {
      // Restore previously captured inline styles.
      savedInlineStyles.forEach(function (entry) {
        if (entry.prev === null) {
          entry.el.style.removeProperty(entry.prop);
        } else {
          entry.el.style.setProperty(entry.prop, entry.prev);
        }
      });
      savedInlineStyles = [];
    }
  }

  function applyInline(el) {
    if (!el || !el.style) return;
    ['user-select', '-webkit-user-select', '-webkit-touch-callout', 'touch-action'].forEach(function (prop) {
      var prev = el.style.getPropertyValue(prop) || null;
      savedInlineStyles.push({ el: el, prop: prop, prev: prev });
    });
    el.style.setProperty('user-select', 'text', 'important');
    el.style.setProperty('-webkit-user-select', 'text', 'important');
    el.style.setProperty('-webkit-touch-callout', 'default', 'important');
    el.style.setProperty('touch-action', 'auto', 'important');
  }

  // Document-level capture blockers — catch xterm handlers no matter where attached.
  function blockEvent(e) {
    if (!selectionMode) return;
    // Only block events that xterm would preventDefault on; we leave click-through alone.
    e.stopImmediatePropagation();
  }
  var blockedEvents = ['touchstart', 'touchmove', 'touchend', 'mousedown', 'selectstart', 'contextmenu'];

  function setSelectionMode(on) {
    if (on === selectionMode) return;
    selectionMode = !!on;
    if (selectionMode) {
      document.documentElement.classList.add('tb-select-mode');
      forceInlineUserSelect(true);
      blockedEvents.forEach(function (evt) {
        document.addEventListener(evt, blockEvent, true);
      });
    } else {
      document.documentElement.classList.remove('tb-select-mode');
      forceInlineUserSelect(false);
      blockedEvents.forEach(function (evt) {
        document.removeEventListener(evt, blockEvent, true);
      });
    }
  }

  // ---- 4. Parent → iframe message dispatcher ----
  window.addEventListener('message', function (e) {
    if (e.origin !== PARENT_ORIGIN) return;
    var msg = e.data;
    if (!msg || typeof msg !== 'object') return;
    switch (msg.type) {
      case 'key':
        if (typeof msg.bytes === 'string') sendBytes(msg.bytes);
        break;
      case 'select-mode':
        setSelectionMode(!!msg.on);
        break;
      case 'ping':
        // Lets the parent re-sync after iframe reload.
        postToParent({ type: CAPTURED_WS && CAPTURED_WS.readyState === 1 ? 'ready' : 'ws-closed' });
        break;
    }
  });

  // Let parent know we're here even before WS opens, so the toolbar can
  // render in a disabled state.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      postToParent({ type: 'bridge-loaded' });
    });
  } else {
    postToParent({ type: 'bridge-loaded' });
  }
})();
