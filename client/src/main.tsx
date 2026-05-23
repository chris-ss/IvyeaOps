import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/workbench.css";

// Apply persisted theme before React mounts so we don't get a flash of the
// wrong theme. Falls back to dark. Keep the key in sync with MainLayout.
const THEME_KEY = "opshub.theme";
const VALID_THEMES = ["dark", "light", "deep-space", "smoke-gold", "catppuccin"] as const;
const saved = localStorage.getItem(THEME_KEY) as string | null;
const theme = VALID_THEMES.includes(saved as any) ? saved! : "dark";
document.documentElement.setAttribute("data-theme", theme);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
