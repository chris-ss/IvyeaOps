import { useEffect, useRef, useState } from "react";
import { getSession, type AgentSession } from "../../../api/agents";

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; session: AgentSession }
  | { kind: "err"; detail: string };

/**
 * Load a hub agent_session by id. Re-fetches whenever the id changes;
 * cancels stale requests via an isActive flag so quick session-switches
 * don't race.
 */
export function useHubSession(sessionId: string | null): {
  state: State;
  session: AgentSession | null;
  reload: () => void;
} {
  const [state, setState] = useState<State>({ kind: "idle" });
  const [tick, setTick] = useState(0);
  const activeRef = useRef(true);

  useEffect(() => () => { activeRef.current = false; }, []);

  useEffect(() => {
    if (!sessionId) {
      setState({ kind: "idle" });
      return;
    }
    let alive = true;
    setState({ kind: "loading" });
    (async () => {
      try {
        const s = await getSession(sessionId);
        if (alive && activeRef.current) setState({ kind: "ok", session: s });
      } catch (e: any) {
        if (alive && activeRef.current) {
          setState({ kind: "err", detail: e?.response?.data?.detail || e?.message || "加载会话失败" });
        }
      }
    })();
    return () => { alive = false; };
  }, [sessionId, tick]);

  const session = state.kind === "ok" ? state.session : null;
  return { state, session, reload: () => setTick((t) => t + 1) };
}
