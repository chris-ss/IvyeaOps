import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/workbench.css";

// Apply persisted theme before React mounts so we don't get a flash of the
// wrong theme. Falls back to dark. Keep the key in sync with MainLayout.
const THEME_KEY = "opshub.theme";
const saved = localStorage.getItem(THEME_KEY);
const theme = saved === "light" || saved === "dark" ? saved : "dark";
document.documentElement.setAttribute("data-theme", theme);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
