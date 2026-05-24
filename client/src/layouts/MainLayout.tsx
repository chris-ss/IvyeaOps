import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { logout } from "../api/client";
import Terminal from "../pages/workbench/Terminal";

type NavItem = {
  to: string;
  icon: string;
  label: string;
  badge?: string;
};

type NavSection = {
  title: string;
  items: NavItem[];
};

const NAV: NavSection[] = [
  {
    title: "运营",
    items: [
      { to: "/", icon: "⌂", label: "首页" },
      { to: "/tools", icon: "⚙", label: "工具箱" },
      { to: "/imgflow", icon: "◧", label: "Listing生成" },
      { to: "/market", icon: "◈", label: "市场调研" },
    ],
  },
  {
    title: "AI 系统",
    items: [
      { to: "/agents", icon: "◇", label: "智能体会话" },
      { to: "/skill", icon: "✦", label: "Skill Studio" },
      { to: "/brain", icon: "▣", label: "GBrain 知识库" },
    ],
  },
  {
    title: "基础设施",
    items: [
      { to: "/terminal", icon: "▶", label: "服务器终端" },
      { to: "/servmon", icon: "◉", label: "服务器监控" },
    ],
  },
  {
    title: "其他",
    items: [
      { to: "/news", icon: "≡", label: "资讯", badge: "3" },
      { to: "/hub-settings", icon: "⊙", label: "系统配置" },
    ],
  },
];

const PATH_LABEL: Record<string, string> = {
  "/": "~/首页",
  "/tools": "~/工具箱",
  "/imgflow": "~/Listing生成",
  "/market": "~/市场调研",
  "/skill": "~/SkillStudio",
  "/brain": "~/GBrain知识库",
  "/agents": "~/智能体会话",
  "/agents-legacy": "~/智能体会话（旧版）",
  "/agent": "~/AgentOS",
  "/cloudcli": "~/CloudCLI",
  "/terminal": "~/服务器终端",
  "/servmon": "~/服务器监控",
  "/news": "~/资讯",
  "/hub-settings": "~/系统配置",
};

export default function MainLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const [termMounted, setTermMounted] = useState(false);
  const THEMES = [
    "dark", "deep-space", "smoke-gold", "catppuccin", "hermes", "light",
    "klein", "mars", "hermes-orange", "burgundy", "mummy",
    "prussian", "tiffany", "titian", "schonbrunn", "bordeaux",
  ] as const;
  type Theme = typeof THEMES[number];
  const THEME_LABELS: Record<Theme, string> = {
    "dark":         "🌲 暗夜",
    "deep-space":   "🌌 星渊",
    "smoke-gold":   "✦ 烟金",
    "catppuccin":   "🔮 紫幕",
    "hermes":       "◆ 幽林",
    "light":        "☀ 月岩",
    "klein":        "◈ 克莱蓝",
    "mars":         "⬡ 马尔绿",
    "hermes-orange":"◉ 爱马橙",
    "burgundy":     "⊕ 勃艮红",
    "mummy":        "△ 木乃棕",
    "prussian":     "▣ 普鲁蓝",
    "tiffany":      "◇ 蒂芙蓝",
    "titian":       "✦ 提香红",
    "schonbrunn":   "⊙ 申布黄",
    "bordeaux":     "⊗ 波尔红",
  };
  const THEME_ICONS: Record<Theme, string> = {
    "dark": "🌲", "deep-space": "🌌", "smoke-gold": "✦",
    "catppuccin": "🔮", "hermes": "◆", "light": "☀",
    "klein": "◈", "mars": "⬡", "hermes-orange": "◉",
    "burgundy": "⊕", "mummy": "△", "prussian": "▣",
    "tiffany": "◇", "titian": "✦", "schonbrunn": "⊙", "bordeaux": "⊗",
  };
  const THEME_NAMES: Record<Theme, string> = {
    "dark": "暗夜", "deep-space": "星渊", "smoke-gold": "烟金",
    "catppuccin": "紫幕", "hermes": "幽林", "light": "月岩",
    "klein": "克莱蓝", "mars": "马尔绿", "hermes-orange": "爱马橙",
    "burgundy": "勃艮红", "mummy": "木乃棕", "prussian": "普鲁蓝",
    "tiffany": "蒂芙蓝", "titian": "提香红", "schonbrunn": "申布黄", "bordeaux": "波尔红",
  };
  const THEME_ACCENTS: Record<Theme, string> = {
    "dark":         "#4ade80",
    "deep-space":   "#60a5fa",
    "smoke-gold":   "#fbbf24",
    "catppuccin":   "#a78bfa",
    "hermes":       "#34d399",
    "light":        "#16a34a",
    "klein":        "#4d7fff",
    "mars":         "#8aad3c",
    "hermes-orange":"#f46020",
    "burgundy":     "#c03060",
    "mummy":        "#c87838",
    "prussian":     "#2d8ab5",
    "tiffany":      "#50c0b8",
    "titian":       "#c86030",
    "schonbrunn":   "#e8b01a",
    "bordeaux":     "#b03280",
  };
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem("opshub.theme") as Theme | null;
    return THEMES.includes(saved as any) ? saved! : "dark";
  });
  const [themePicker, setThemePicker] = useState(false);
  const themePickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!themePicker) return;
    const handler = (e: MouseEvent) => {
      if (themePickerRef.current && !themePickerRef.current.contains(e.target as Node))
        setThemePicker(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [themePicker]);
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("opshub.sidebar.collapsed") === "1" || window.innerWidth <= 680,
  );
  const [mobileMenu, setMobileMenu] = useState(false);
  const [isMobile, setIsMobile] = useState(() => window.innerWidth <= 900);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth <= 900);
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  // Once the user visits /terminal, keep it mounted forever.
  useEffect(() => {
    if (location.pathname === "/terminal") setTermMounted(true);
  }, [location.pathname]);
  const [clock, setClock] = useState("");

  // Clock
  useEffect(() => {
    const tick = () =>
      setClock(
        new Date().toLocaleTimeString("zh-CN", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }),
      );
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, []);

  const selectTheme = (t: Theme) => {
    setTheme(t);
    document.documentElement.setAttribute("data-theme", t);
    localStorage.setItem("opshub.theme", t);
    setThemePicker(false);
  };

  const toggleSidebar = () => {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem("opshub.sidebar.collapsed", next ? "1" : "0");
  };

  const handleLogout = async () => {
    try {
      await logout();
    } finally {
      navigate("/login");
    }
  };

  const path = PATH_LABEL[location.pathname] || "~/";

  return (
    <div className="app">
      {/* SIDEBAR */}
      {isMobile && mobileMenu && <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", zIndex: 998 }} onClick={() => setMobileMenu(false)} />}
      <aside className={"sb" + (collapsed && !mobileMenu ? " collapsed" : "")} style={isMobile ? { position: "fixed", zIndex: 999, height: "100%", width: 196, minWidth: 196, overflow: "auto", left: mobileMenu ? 0 : -200, transition: "left .2s ease" } : undefined}>
        <div className="sb-logo">
          <div className="sb-logo-name" title="个人工作台">
            <span className="sb-logo-icon">◆</span>
            <span className="sb-logo-text">个人工作台</span>
          </div>
          <button
            className="sb-toggle"
            onClick={toggleSidebar}
            title={collapsed ? "展开侧边栏" : "收起侧边栏"}
            aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
          >
            {collapsed ? "▶" : "◀"}
          </button>
        </div>
        <nav>
          {NAV.map((sec) => (
            <div key={sec.title}>
              <div className="ns">{sec.title}</div>
              {sec.items.map((it) => (
                <NavLink
                  key={it.to}
                  to={it.to}
                  end={it.to === "/"}
                  className={({ isActive }) => "ni" + (isActive ? " active" : "")}
                  title={collapsed ? it.label : undefined}
                  onClick={() => isMobile && setMobileMenu(false)}
                >
                  <i className="ic">{it.icon}</i>
                  <span className="ni-label">{it.label}</span>
                  {it.badge && <span className="nb">{it.badge}</span>}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sb-bot">
          <div className="dot" />
          <span className="sb-bot-text" style={{ fontSize: 10, color: "var(--t3)" }}>
            All systems online
          </span>
        </div>
      </aside>

      {/* MAIN */}
      <div className="main">
        <div className="topbar">
          {isMobile && <button className="tbtn" onClick={() => setMobileMenu(!mobileMenu)} style={{ marginRight: 4 }}>☰</button>}
          <div className="tb-path">
            <b>{path}</b>
          </div>
          <div className="tb-r">
            <div className="tb-time">{clock}</div>
            <button
              className="tbtn"
              onClick={() => {
                if ((window as any).OpsApp?.reload) {
                  (window as any).OpsApp.reload();
                } else {
                  window.location.reload();
                }
              }}
              title="刷新页面"
            >
              ↻
            </button>
            <div ref={themePickerRef} style={{ position: "relative", display: "flex", alignItems: "center" }}>
              <button
                className="tbtn"
                onClick={() => setThemePicker(!themePicker)}
                style={{ minWidth: 72 }}
                title="切换主题"
              >
                {THEME_LABELS[theme]}
              </button>
              {themePicker && (
                <div className="theme-picker">
                  {THEMES.map((t) => (
                    <button
                      key={t}
                      className={"theme-picker-card" + (t === theme ? " active" : "")}
                      onClick={() => selectTheme(t)}
                    >
                      <span className="theme-picker-dot" style={{ background: THEME_ACCENTS[t] }} />
                      <span className="theme-picker-icon">{THEME_ICONS[t]}</span>
                      <span className="theme-picker-name">{THEME_NAMES[t]}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button className="tbtn" onClick={handleLogout} title="退出登录">
              ↩ 退出
            </button>
          </div>
        </div>
        <div className={"content" + (
          location.pathname === "/agents" ||
          location.pathname === "/agents-legacy"
            ? " content-fullpage" : ""
        )}>
          {/* Terminal is always mounted (after first visit) but hidden when
              not active, so the iframe WebSocket survives tab switches. */}
          {termMounted && (
            <div style={location.pathname === "/terminal" ? { display: "contents" } : { position: "absolute", width: 0, height: 0, overflow: "hidden", opacity: 0, pointerEvents: "none" }}>
              <Terminal />
            </div>
          )}
          {location.pathname !== "/terminal" && <Outlet />}
        </div>
      </div>
    </div>
  );
}
