import { TAB_GLYPHS, TAB_LABELS, type TabKey } from "./tabs";

type Props = {
  availableTabs: TabKey[];
  activeTab: TabKey | null;
  onTabChange: (t: TabKey) => void;
  onOpenSidebar: () => void;
};

/**
 * Bottom navigation visible on narrow viewports (toggled by CSS via
 * .ws-mobile-only). Tap a tab to switch the main content; tap the
 * leftmost project icon to open the sidebar drawer.
 */
export default function MobileBottomNav({ availableTabs, activeTab, onTabChange, onOpenSidebar }: Props) {
  return (
    <nav className="ws-bottom-nav ws-mobile-only">
      <button
        className="ws-bn-btn"
        onClick={onOpenSidebar}
        title="项目列表"
        aria-label="项目列表"
      >
        <span className="ws-bn-glyph">⊟</span>
        <span className="ws-bn-label">项目</span>
      </button>
      {availableTabs.map((t) => (
        <button
          key={t}
          className={"ws-bn-btn" + (activeTab === t ? " active" : "")}
          onClick={() => onTabChange(t)}
        >
          <span className="ws-bn-glyph">{TAB_GLYPHS[t]}</span>
          <span className="ws-bn-label">{TAB_LABELS[t]}</span>
        </button>
      ))}
    </nav>
  );
}
