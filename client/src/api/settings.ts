import { api } from "./client";

export interface HubSettings {
  // AI synthesis
  apimart_key: string;
  apimart_base: string;
  // Comma-separated text-AI fallback order. Apimart not included by default
  // because most Apimart keys only grant image models, not Claude text.
  text_ai_providers: string;
  // Market data
  sorftime_key: string;
  // Listing Generator
  imgflow_url: string;
  // GBrain
  gbrain_bin: string;
  brain_root: string;
  openai_api_key: string;
  // Feishu alerts
  alert_webhook: string;
  alert_app_id: string;
  alert_app_secret: string;
  alert_chat_id: string;
  // Alert thresholds
  alert_threshold: number;
  alert_sustain: number;
  alert_cooldown: number;
  // Embedded URLs
  dashboard_url: string;
  terminal_url: string;
  // External integrations
  hermes_bin: string;
  codex_bin: string;
  claude_bin: string;
  kiro_cli_bin: string;
  hermes_db: string;
  codex_db: string;
  feishu_codex_db: string;
  kiro_gateway_db: string;
  kiro_cli_db: string;
  kiro_cli_sessions_dir: string;
  claude_projects_dir: string;
  hermes_node_bin: string;
  bun_bin: string;
  // Auto bug-fix toggle (admin-only feature)
  autofix_enabled: boolean;
  // SIF — 深度分析工具箱，独立 key（mcp.sif.com Bearer token）
  sif_key: string;
  // SellerSprite — separate key, auto-registers stdio MCP server in Hermes
  sellersprite_key: string;
  // Account (password_hash not exposed to frontend)
}

export interface SettingsResp {
  settings: HubSettings;
  secret_keys: string[];
}

export interface RunnerStatus {
  ok: boolean;
  detail: string;
}

export interface HealthResp {
  apimart: RunnerStatus;
  sorftime: RunnerStatus;
  imgflow: RunnerStatus;
  gbrain_bin: RunnerStatus;
  brain_root: RunnerStatus;
  openai: RunnerStatus;
  runners: {
    hermes: RunnerStatus;
    codex: RunnerStatus;
    claude: RunnerStatus;
  };
  integrations?: Record<string, RunnerStatus>;
}

export async function getSettings(): Promise<SettingsResp> {
  const { data } = await api.get<SettingsResp>("/settings");
  return data;
}

export async function patchSettings(updates: Partial<HubSettings>): Promise<SettingsResp> {
  const { data } = await api.patch<SettingsResp>("/settings", { settings: updates });
  return data;
}

export async function getHealth(): Promise<HealthResp> {
  const { data } = await api.get<HealthResp>("/settings/health", { timeout: 10000 });
  return data;
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await api.post("/auth/change-password", { old_password: oldPassword, new_password: newPassword });
}

export interface TestResult {
  ok: boolean;
  detail: string;
}

export interface AutodetectResp {
  suggestions: Partial<Record<keyof HubSettings, string>>;
  scanned: string[];
}

export async function testSetting(key: keyof HubSettings, value?: string): Promise<TestResult> {
  const { data } = await api.post<TestResult>("/settings/test", { key, value }, { timeout: 15000 });
  return data;
}

export async function autodetectSettings(): Promise<AutodetectResp> {
  const { data } = await api.post<AutodetectResp>("/settings/autodetect", {}, { timeout: 10000 });
  return data;
}
