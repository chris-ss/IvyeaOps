import { useEffect, useRef, useState } from "react";
import KeywordMonitor from "./home/KeywordMonitor";
import AsinMonitor from "./home/AsinMonitor";
import AlertStrip from "./home/AlertStrip";
import CategoryWatch from "./home/CategoryWatch";
import MarketTraffic from "./home/MarketTraffic";

const STORAGE_MKT = "ivyea-ops-pulse-marketplace";
const STORAGE_TAB = "ivyea-ops-home-tab";

const FLAG_URL = (code: string) => `https://flagcdn.com/w20/${code === "UK" ? "gb" : code.toLowerCase()}.png`;
const MARKETPLACES = [
  { code: "US", name: "美国" }, { code: "UK", name: "英国" },
  { code: "DE", name: "德国" }, { code: "JP", name: "日本" },
  { code: "CA", name: "加拿大" }, { code: "FR", name: "法国" },
  { code: "AU", name: "澳大利亚" }, { code: "IT", name: "意大利" },
];

type HomeTab = "keyword" | "competitor" | "own" | "category" | "market";

const TABS: { key: HomeTab; label: string; icon: string }[] = [
  { key: "market", label: "大盘流量", icon: "↗" },
  { key: "keyword", label: "关键词", icon: "◈" },
  { key: "competitor", label: "竞品监控", icon: "⊞" },
  { key: "own", label: "自有 ASIN", icon: "★" },
  { key: "category", label: "类目大盘", icon: "☰" },
];

export default function Home() {
  const [marketplace, setMarketplace] = useState(() => localStorage.getItem(STORAGE_MKT) || "US");
  const [tab, setTab] = useState<HomeTab>(() => (localStorage.getItem(STORAGE_TAB) as HomeTab) || "keyword");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [alertReloadKey, setAlertReloadKey] = useState(0);
  const pickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => { localStorage.setItem(STORAGE_MKT, marketplace); }, [marketplace]);
  useEffect(() => { localStorage.setItem(STORAGE_TAB, tab); }, [tab]);

  useEffect(() => {
    if (!pickerOpen) return;
    const handler = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) setPickerOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [pickerOpen]);

  const today = new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "short" });
  const currentMkt = MARKETPLACES.find(m => m.code === marketplace) ?? MARKETPLACES[0];

  return (
    <div className="home-cockpit">
      {/* ── Top bar: title + date + global marketplace ── */}
      <div className="home-topbar">
        <span className="home-title">
          <span style={{ color: "var(--acc)" }}>◧</span> 运营驾驶舱
          <span className="home-date">{today}</span>
        </span>
        <div className="market-mkt-wrap" ref={pickerRef}>
          <button className="market-mkt-btn" onClick={() => setPickerOpen(o => !o)} title="选择站点">
            <span className="market-mkt-flag"><img src={FLAG_URL(currentMkt.code)} alt={currentMkt.code} style={{width:16,height:12,verticalAlign:"middle"}} /></span>
            <span className="market-mkt-code">{currentMkt.code}</span>
            <span className="market-mkt-arrow">{pickerOpen ? "▴" : "▾"}</span>
          </button>
          {pickerOpen && (
            <div className="market-mkt-dropdown hide-mobile-picker">
              {MARKETPLACES.map(m => (
                <button
                  key={m.code}
                  className={"market-mkt-option" + (marketplace === m.code ? " active" : "")}
                  onClick={() => { setMarketplace(m.code); setPickerOpen(false); }}
                >
                  <span><img src={FLAG_URL(m.code)} alt={m.code} style={{width:16,height:12,verticalAlign:"middle"}} /></span>
                  <span className="market-mkt-option-code">{m.code}</span>
                  <span className="market-mkt-option-name">{m.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Alert strip ── */}
      <AlertStrip reloadKey={alertReloadKey} onJump={(kind) => setTab(kind)} />

      {/* ── Tabs ── */}
      <div className="home-tabs">
        {TABS.map(t => (
          <button
            key={t.key}
            className={"home-tab" + (tab === t.key ? " active" : "")}
            onClick={() => setTab(t.key)}
          >
            <span className="home-tab-icon">{t.icon}</span>
            <span className="home-tab-label">{t.label}</span>
          </button>
        ))}
      </div>

      {/* ── Tab body ── */}
      <div className="home-tab-body wb-enter" key={tab}>
        {tab === "keyword" && <KeywordMonitor marketplace={marketplace} />}
        {tab === "competitor" && (
          <AsinMonitor kind="competitor" marketplace={marketplace} onChanged={() => setAlertReloadKey(k => k + 1)} />
        )}
        {tab === "own" && (
          <AsinMonitor kind="own" marketplace={marketplace} onChanged={() => setAlertReloadKey(k => k + 1)} />
        )}
        {tab === "category" && <CategoryWatch marketplace={marketplace} />}
        {tab === "market" && <MarketTraffic marketplace={marketplace} />}
      </div>

      {/* ── Mobile bottom-sheet marketplace picker ── */}
      {pickerOpen && (
        <div className="show-mobile-picker">
          <div className="market-sheet-backdrop" onClick={() => setPickerOpen(false)} />
          <div className="market-sheet">
            <div className="market-sheet-handle" />
            <div className="market-sheet-title">选择站点</div>
            <div className="market-sheet-grid">
              {MARKETPLACES.map(m => (
                <button
                  key={m.code}
                  className={"market-sheet-item" + (marketplace === m.code ? " active" : "")}
                  onClick={() => { setMarketplace(m.code); setPickerOpen(false); }}
                >
                  <span className="market-sheet-flag"><img src={FLAG_URL(m.code)} alt={m.code} style={{width:16,height:12,verticalAlign:"middle"}} /></span>
                  <span className="market-sheet-code">{m.code}</span>
                  <span className="market-sheet-name">{m.name}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
