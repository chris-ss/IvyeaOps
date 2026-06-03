import { createContext, useContext, useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import MainLayout from "./layouts/MainLayout";
import ErrorBoundary from "./components/ErrorBoundary";
import { ConfirmProvider } from "./components/ConfirmDialog";
import AutoFixProvider from "./components/AutoFixProvider";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";
import Home from "./pages/workbench/Home";
import Tools from "./pages/workbench/Tools";
import SkillStudio from "./pages/skill/SkillStudio";
import StatsOverview from "./pages/skill/StatsOverview";
import SkillBrowse from "./pages/skill/SkillBrowse";
import TrashList from "./pages/skill/TrashList";
import SettingsPage from "./pages/skill/SettingsPage";
import Terminal from "./pages/workbench/Terminal";
import ServerMonitor from "./pages/workbench/ServerMonitor";
import News from "./pages/workbench/News";
import Brain from "./pages/workbench/Brain";
import ListingWorkbench from "./pages/workbench/ListingWorkbench";
import Agents from "./pages/workbench/Agents";
import Market from "./pages/workbench/Market";
import Playbook from "./pages/workbench/Playbook";
import HubSettings from "./pages/workbench/HubSettings";
import Setup from "./pages/Setup";
import FreightQuote from "./pages/workbench/FreightQuote";
import Users from "./pages/workbench/Users";
import Assistant from "./pages/workbench/Assistant";
import ImageGen from "./pages/workbench/ImageGen";
import IdeaSkill from "./pages/workbench/IdeaSkill";
import SkillTools from "./pages/workbench/SkillTools";
import SkillHub from "./pages/workbench/SkillHub";
import DeepAnalysis from "./pages/workbench/DeepAnalysis";
import { me } from "./api/client";
import { getSetupStatus, type SetupChecks } from "./api/setup";

// ---------------------------------------------------------------------------
// Auth context — exposes the current user's role to all pages / the layout.
// ---------------------------------------------------------------------------

export type Role = "admin" | "user";
const AuthCtx = createContext<{ role: Role; username: string; permissions: string[] }>({ role: "user", username: "", permissions: [] });
export const useAuth = () => useContext(AuthCtx);

// ---------------------------------------------------------------------------
// Auth guard — also checks whether the first-run wizard is needed (admin only).
// ---------------------------------------------------------------------------

type AuthState = "loading" | "setup" | "ok" | "no";

function RequireAuth({ children }: { children: JSX.Element }) {
  const [state, setState] = useState<AuthState>("loading");
  const [setupChecks, setSetupChecks] = useState<SetupChecks | null>(null);
  const [auth, setAuth] = useState<{ role: Role; username: string; permissions: string[] }>({ role: "user", username: "", permissions: [] });

  useEffect(() => {
    me()
      .then(async (u) => {
        setAuth({ role: u.role, username: u.username, permissions: u.permissions || [] });
        // First-run wizard is admin-only; registered users skip it.
        if (u.role !== "admin") {
          setState("ok");
          return;
        }
        try {
          const s = await getSetupStatus();
          if (s.needs_setup) {
            setSetupChecks(s.checks);
            setState("setup");
          } else {
            setState("ok");
          }
        } catch {
          setState("ok");
        }
      })
      .catch(() => setState("no"));
  }, []);

  if (state === "loading") {
    return (
      <div
        style={{
          display: "grid",
          placeItems: "center",
          height: "100vh",
          background: "var(--bg)",
          color: "var(--t3)",
          fontSize: 11,
          letterSpacing: ".1em",
        }}
      >
        <span>
          <span className="spin" style={{ marginRight: 8 }} />
          AUTHENTICATING...
        </span>
      </div>
    );
  }
  if (state === "no") return <Navigate to="/login" replace />;
  if (state === "setup" && setupChecks) return <Setup checks={setupChecks} />;
  return (
    <AuthCtx.Provider value={auth}>
      <AutoFixProvider>{children}</AutoFixProvider>
    </AuthCtx.Provider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ConfirmProvider>
      <ErrorBoundary>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <MainLayout />
              </RequireAuth>
            }
          >
            <Route index element={<Home />} />
            <Route path="tools" element={<Tools />} />
            <Route path="skill" element={<SkillStudio />}>
              <Route index element={<StatsOverview />} />
              <Route path="browse" element={<SkillBrowse />} />
              <Route path="trash" element={<TrashList />} />
              <Route path="settings" element={<SettingsPage />} />
            </Route>
            <Route path="terminal" element={<Terminal />} />
            <Route path="servmon" element={<ServerMonitor />} />
            <Route path="news" element={<News />} />
            <Route path="brain" element={<Brain />} />
            <Route path="agents" element={<Agents />} />
            <Route path="listing" element={<ListingWorkbench />} />
            <Route path="freight" element={<FreightQuote />} />
            <Route path="market" element={<Market />} />
            <Route path="playbook" element={<Playbook />} />
            <Route path="users" element={<Users />} />
            <Route path="assistant" element={<Assistant />} />
            <Route path="imagegen" element={<ImageGen />} />
            <Route path="idea-skill" element={<IdeaSkill />} />
            <Route path="skill-tools" element={<SkillTools />} />
            <Route path="skill-hub" element={<SkillHub />} />
            <Route path="deep-analysis" element={<DeepAnalysis />} />
            <Route path="hub-settings" element={<HubSettings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </ErrorBoundary>
      </ConfirmProvider>
    </BrowserRouter>
  );
}
