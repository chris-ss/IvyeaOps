import { api } from "./client";

export interface SetupChecks {
  password_set: boolean;
  any_agent_found: boolean;
  agents: Record<string, boolean>;
  apimart_set: boolean;
}

export interface SetupStatusResp {
  needs_setup: boolean;
  setup_done: boolean;
  checks: SetupChecks;
}

export async function getSetupStatus(): Promise<SetupStatusResp> {
  const { data } = await api.get<SetupStatusResp>("/setup/status");
  return data;
}

export async function completeSetup(): Promise<void> {
  await api.post("/setup/complete", {});
}

// Returns the EventSource URL for streaming agent install logs.
export function installAgentStreamUrl(agent: string): string {
  return `/api/setup/install-stream?agent=${encodeURIComponent(agent)}`;
}
