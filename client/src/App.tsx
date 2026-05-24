import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import MainLayout from "./layouts/MainLayout";
import ErrorBoundary from "./components/ErrorBoundary";
import { ConfirmProvider } from "./components/ConfirmDialog";
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
import ImageWorkflow from "./pages/workbench/ImageWorkflow";
import ListingGenerator from "./pages/workbench/ListingGenerator.jsx";
import AgentChat from "./pages/workbench/AgentChat";
import Workspace from "./pages/workbench/workspace/Workspace";
import Market from "./pages/workbench/Market";
import HubSettings from "./pages/workbench/HubSettings";
import Setup from "./pages/Setup";
import { me } from "./api/client";
import { getSetupStatus, type SetupChecks } from "./api/setup";

// ---------------------------------------------------------------------------
// Auth guard — also checks whether the first-run wizard is needed.
// ---------------------------------------------------------------------------

type AuthState = "loading" | "setup" | "ok" | "no";

function RequireAuth({ children }: { children: JSX.Element }) {
  const [state, setState] = useState<AuthState>("loading");
  const [setupChecks, setSetupChecks] = useState<SetupChecks | null>(null);

  useEffect(() => {
    me()
      .then(async () => {
        try {
          const s = await getSetupStatus();
          if (s.needs_setup) {
            setSetupChecks(s.checks);
            setState("setup");
          } else {
            setState("ok");
          }
        } catch {
          // If setup endpoint fails (older deploy without the route), just proceed.
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
  return children;
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
            {/* /agents routes to the new Workspace; old AgentChat is
                kept at /agents-legacy as an escape hatch during the
                transition. After a few weeks of stable use, both
                /agents-legacy and AgentChat.tsx can be deleted. */}
            <Route path="agents" element={<Workspace />} />
            <Route path="agents-legacy" element={<AgentChat />} />
            <Route path="imgflow" element={<ListingGenerator />} />
            <Route path="market" element={<Market />} />
            <Route path="hub-settings" element={<HubSettings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </ErrorBoundary>
      </ConfirmProvider>
    </BrowserRouter>
  );
}
