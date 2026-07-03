import type { LLMProvider } from '../../types/app';

export type ProviderAuthStatus = {
  authenticated: boolean;
  email: string | null;
  method: string | null;
  error: string | null;
  loading: boolean;
};

export type ProviderAuthStatusMap = Record<LLMProvider, ProviderAuthStatus>;

// hermes is included so its auth status is actually fetched (it reports
// method=api_key, which resolves the "checking…" spinner and hides the
// spurious Login button — hermes authenticates via config.yaml/.env keys).
export const CLI_PROVIDERS: LLMProvider[] = ['claude', 'cursor', 'codex', 'gemini', 'opencode', 'hermes', 'ivyea'];

export const PROVIDER_AUTH_STATUS_ENDPOINTS: Record<LLMProvider, string> = {
  claude: '/api/providers/claude/auth/status',
  cursor: '/api/providers/cursor/auth/status',
  codex: '/api/providers/codex/auth/status',
  gemini: '/api/providers/gemini/auth/status',
  opencode: '/api/providers/opencode/auth/status',
  hermes: '/api/providers/hermes/auth/status',
  agy: '/api/providers/agy/auth/status',
  ivyea: '/api/providers/ivyea/auth/status',
};

export const createInitialProviderAuthStatusMap = (loading = true): ProviderAuthStatusMap => ({
  claude: { authenticated: false, email: null, method: null, error: null, loading },
  cursor: { authenticated: false, email: null, method: null, error: null, loading },
  codex: { authenticated: false, email: null, method: null, error: null, loading },
  gemini: { authenticated: false, email: null, method: null, error: null, loading },
  opencode: { authenticated: false, email: null, method: null, error: null, loading },
  hermes: { authenticated: false, email: null, method: null, error: null, loading },
  agy: { authenticated: false, email: null, method: null, error: null, loading },
  ivyea: { authenticated: false, email: null, method: null, error: null, loading },
});
