import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/workbench.css";
import { applyAppearance } from "./lib/appearance";

// Apply persisted theme before React mounts so we don't get a flash of the
// wrong theme. Falls back to dark. Keep the key in sync with MainLayout.
const THEME_KEY = "ivyea-ops.theme";
const VALID_THEMES = ["dark", "light", "deep-space", "smoke-gold", "catppuccin", "hermes"] as const;
const saved = localStorage.getItem(THEME_KEY) as string | null;
const theme = VALID_THEMES.includes(saved as any) ? saved! : "dark";
document.documentElement.setAttribute("data-theme", theme);

// Apply persisted appearance (user font override + global zoom) before mount,
// same reason as theme — avoid a flash of the wrong font/size.
applyAppearance();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
