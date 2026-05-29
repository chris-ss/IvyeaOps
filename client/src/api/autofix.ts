// API client for the auto bug-fix flow + a tiny error sink that the axios
// interceptor (api/client.ts) feeds. The sink is a plain module singleton so
// the non-React interceptor can hand failures to the React provider without a
// circular runtime dependency (both only touch each other inside functions).
import { api } from "./client";

export type AutofixErrorCtx = {
  feature?: string;
  endpoint?: string;
  method?: string;
  status?: number;
  detail?: string;
};

export type AutofixJob = {
  id: string;
  status:
    | "running"
    | "diagnosed"
    | "applying"
    | "applied"
    | "failed"
    | "rejected"
    | "restarting";
  summary: string;
  diff: string;
  changed_files: string[];
  needs_restart: boolean;
  needs_rebuild: boolean;
  error: AutofixErrorCtx;
  error_detail: string;
  created_at: number;
  updated_at: number;
};

export async function autofixStatus() {
  const { data } = await api.get<{ enabled: boolean; job: AutofixJob | null }>(
    "/autofix/status",
  );
  return data;
}

export async function autofixDiagnose(ctx: AutofixErrorCtx) {
  const { data } = await api.post<AutofixJob>("/autofix/diagnose", ctx, {
    timeout: 20000,
  });
  return data;
}

export async function autofixGet(id: string) {
  const { data } = await api.get<AutofixJob>(`/autofix/${id}`);
  return data;
}

export async function autofixApply(id: string) {
  const { data } = await api.post<AutofixJob>(`/autofix/${id}/apply`, {}, { timeout: 700000 });
  return data;
}

export async function autofixRestart(id: string) {
  const { data } = await api.post<{ ok: boolean }>(`/autofix/${id}/restart`, {});
  return data;
}

export async function autofixRollback(id: string) {
  const { data } = await api.post<AutofixJob>(`/autofix/${id}/rollback`, {}, { timeout: 700000 });
  return data;
}

export async function autofixReject(id: string) {
  const { data } = await api.post<{ ok: boolean }>(`/autofix/${id}/reject`, {});
  return data;
}

// ── error sink ─────────────────────────────────────────────────────────────
// Enabled is flipped on by the provider after it confirms the feature is on
// AND the current user is admin. While false, reportApiError is a no-op, so a
// disabled feature costs nothing on the hot path.
let _enabled = false;
let _sink: ((ctx: AutofixErrorCtx) => void) | null = null;

export function setAutofixEnabled(on: boolean) {
  _enabled = on;
}

export function registerAutofixSink(fn: ((ctx: AutofixErrorCtx) => void) | null) {
  _sink = fn;
}

export function reportApiError(ctx: AutofixErrorCtx) {
  if (!_enabled || !_sink) return;
  // Don't let the repair API's own calls trigger a repair loop.
  if ((ctx.endpoint || "").includes("/autofix")) return;
  try {
    _sink(ctx);
  } catch {
    /* never let reporting break the original request flow */
  }
}
