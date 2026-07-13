/* Skill Tools API client */
import { api } from "./client";
import type { SseEvent } from "./deepAnalysis";
export type { SseEvent } from "./deepAnalysis";
import { consumeSSE } from "./deepAnalysis";

export interface SkillToolMeta {
  name: string;
  category: string | null;
  description: string | null;
  description_zh: string | null;
  icon: string;
  inputs: SkillInput[];
  has_execution: boolean;
  pinned?: boolean;
  // Tool Spec (from the frontmatter `tool:` block; absent on legacy skills)
  kind?: string | null;          // report | transform | lookup | workflow
  runtime?: string | null;       // llm-only | mcp
  output_format?: string;        // markdown | text | table
  exportable?: boolean;
  sample_params?: Record<string, unknown>;
}

export interface SkillInput {
  name: string;
  type: string;       // text, select, number, textarea
  label: string;
  required: boolean;
  placeholder: string;
  default: string;
  options: string[];
}

export interface SkillToolListResponse {
  tools: SkillToolMeta[];
  categories: Record<string, number>;
}

export async function listTools(category?: string, q?: string): Promise<SkillToolListResponse> {
  const params: Record<string, string> = {};
  if (category) params.category = category;
  if (q) params.q = q;
  const { data } = await api.get("/skill-tools/list", { params });
  return data;
}

export async function listPinnedTools(): Promise<SkillToolMeta[]> {
  const { data } = await api.get("/skill-tools/pinned");
  return data;
}

export async function pinTool(skillName: string, pinned: boolean): Promise<SkillToolMeta> {
  const { data } = await api.post("/skill-tools/pin", { skill_name: skillName, pinned });
  return data;
}

// ── Execution history ───────────────────────────────────────────────────

export interface SkillRunSummary {
  id: string;
  skill_name: string;
  status: string;          // done | error | empty
  provider: string;
  runtime: string;
  started_at: string;
  elapsed_s: number;
  error: string | null;
  params: Record<string, string>;
  preview: string;
}

export interface SkillRunDetail extends SkillRunSummary {
  output: string;
  user: string;
}

export interface RepairResult {
  name: string;
  frontmatter: Record<string, unknown>;
  body: string;
  preview: string;
  validation: { ok: boolean; errors: string[]; warnings: string[] };
}

export async function listRuns(skillName: string, limit = 50): Promise<SkillRunSummary[]> {
  const { data } = await api.get("/skill-tools/runs", { params: { skill_name: skillName, limit } });
  return data;
}

export async function getRun(skillName: string, runId: string): Promise<SkillRunDetail> {
  const { data } = await api.get(`/skill-tools/runs/${runId}`, { params: { skill_name: skillName } });
  return data;
}

export async function deleteRun(skillName: string, runId: string): Promise<void> {
  await api.delete(`/skill-tools/runs/${runId}`, { params: { skill_name: skillName } });
}

export async function repairTool(skillName: string, error: string): Promise<RepairResult> {
  const { data } = await api.post(
    "/skill-tools/repair",
    { skill_name: skillName, error },
    { timeout: 300000 },
  );
  return data;
}

/** AI 工具化：为文档型 skill 生成 Tool Spec（参数表单），审核制预览。 */
export async function enrichTool(skillName: string): Promise<RepairResult> {
  const { data } = await api.post(
    "/skill-tools/enrich",
    { skill_name: skillName },
    { timeout: 300000 },
  );
  return data;
}

export function runTool(
  skillName: string,
  params: Record<string, string>,
  onEvent: (evt: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return fetch("/api/skill-tools/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ skill_name: skillName, params }),
    signal,
  }).then((resp) => {
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return consumeSSE(resp, onEvent);
  });
}
