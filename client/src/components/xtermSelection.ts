const GUARD_EVENTS: Array<keyof DocumentEventMap> = [
  "touchstart",
  "touchmove",
  "touchend",
  "mousedown",
  "mousemove",
  "mouseup",
  "selectstart",
  "click",
];

export function isTouchViewport(): boolean {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia("(pointer: coarse)").matches ||
    window.matchMedia("(max-width: 768px)").matches
  );
}

export function enableNativeSelectionMode(root: HTMLElement): () => void {
  const styleTargets = Array.from(
    root.querySelectorAll<HTMLElement>(
      ".xterm, .xterm-screen, .xterm-rows, .xterm-rows > div, .xterm-rows span",
    ),
  );
  const helperTextareas = Array.from(root.querySelectorAll<HTMLElement>(".xterm-helper-textarea"));

  const restoreFns: Array<() => void> = [];

  styleTargets.forEach((el) => {
    const prevUserSelect = el.style.userSelect;
    const prevWebkitUserSelect = (el.style as CSSStyleDeclaration & { webkitUserSelect?: string }).webkitUserSelect || "";
    const prevCursor = el.style.cursor;
    el.style.userSelect = "text";
    (el.style as CSSStyleDeclaration & { webkitUserSelect?: string }).webkitUserSelect = "text";
    el.style.cursor = "text";
    restoreFns.push(() => {
      el.style.userSelect = prevUserSelect;
      (el.style as CSSStyleDeclaration & { webkitUserSelect?: string }).webkitUserSelect = prevWebkitUserSelect;
      el.style.cursor = prevCursor;
    });
  });

  helperTextareas.forEach((el) => {
    const prev = el.style.pointerEvents;
    el.style.pointerEvents = "none";
    if (document.activeElement === el) {
      (document.activeElement as HTMLElement | null)?.blur?.();
    }
    restoreFns.push(() => {
      el.style.pointerEvents = prev;
    });
  });

  const guard = (event: Event) => {
    const target = event.target;
    if (!(target instanceof Node)) return;
    if (!root.contains(target)) return;
    event.stopImmediatePropagation();
  };

  GUARD_EVENTS.forEach((type) => document.addEventListener(type, guard, true));
  restoreFns.push(() => {
    GUARD_EVENTS.forEach((type) => document.removeEventListener(type, guard, true));
  });

  return () => {
    restoreFns.reverse().forEach((fn) => fn());
  };
}

export function getSelectedTerminalText(term: any): string {
  const native = typeof window !== "undefined" ? window.getSelection?.()?.toString() || "" : "";
  if (native.trim()) return native;
  if (typeof term?.getSelection === "function") {
    const selected = term.getSelection();
    if (selected && String(selected).trim()) return String(selected);
  }
  return "";
}

export function getVisibleTerminalText(root: HTMLElement | null): string {
  if (!root) return "";
  const rows = Array.from(root.querySelectorAll<HTMLElement>(".xterm-rows > div"));
  return rows
    .map((row) => (row.textContent || "").replace(/\u00a0/g, " "))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
