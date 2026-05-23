// Shell utilities — message parsing, ANSI helpers.
// Mirrors patterns from siteboon/claudecodeui's shell/utils, adapted to
// ops-hub's WS message shape ({type:'snapshot'|'output'|'exit'|'error'|'pong'}).

const OSC_COLOR_REPLY = /\x1b\](10|11);(?:rgb:[0-9a-fA-F/]+|\?)(?:\x07|\x1b\\)/g;
const BARE_OSC_COLOR_REPLY = /\](10|11);rgb:[0-9a-fA-F/]+/g;

export type ShellInbound =
  | { type: "snapshot"; data: string }
  | { type: "output"; data: string }
  | { type: "exit"; code: number | null }
  | { type: "error"; detail: string }
  | { type: "pong"; t: number };

export type ShellOutbound =
  | { type: "input"; data: string }
  | { type: "resize"; cols: number; rows: number }
  | { type: "ping" };

/** Strip OSC color queries that some terminals send back as input. */
export function stripAutoReplies(data: string): string {
  if (!data) return data;
  let next = data.replace(OSC_COLOR_REPLY, "");
  next = next.replace(BARE_OSC_COLOR_REPLY, "");
  return next;
}

/** Safely parse a backend WS frame; returns null on malformed input. */
export function parseShellMessage(raw: string): ShellInbound | null {
  try {
    const m = JSON.parse(raw);
    if (m && typeof m === "object" && typeof m.type === "string") {
      return m as ShellInbound;
    }
  } catch {
    /* ignore */
  }
  return null;
}

/** Try to send a JSON message; no-op when the socket isn't open. */
export function sendSocketMessage(ws: WebSocket | null, msg: ShellOutbound): boolean {
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  try {
    ws.send(JSON.stringify(msg));
    return true;
  } catch {
    return false;
  }
}
