import { api } from "./client";

export type IvyeaAgentStatus = {
  ok: boolean;
  available: boolean;
  base_url: string;
  token_configured: boolean;
  health?: any;
  error?: string;
};

export type IvyeaChatResult = {
  ok: boolean;
  session_id?: string;
  text?: string;
  events?: { type: string; text?: string }[];
  error?: string;
  detail?: string;
  model?: any;
};

export type IvyeaChatSession = {
  id: string;
  updated?: number;
  turns?: number;
  preview?: string;
};

export type IvyeaChatSessionDetail = {
  id: string;
  created?: number;
  updated?: number;
  model?: string;
  usage?: any;
  messages: { role: string; content: string }[];
};

export type RetrievalStatus = {
  ok: boolean;
  index: {
    enabled?: boolean;
    backend?: string;
    chunks?: number;
    knowledge_cards?: number;
    memory_chunks?: number;
    needs_rebuild?: boolean;
    [key: string]: any;
  };
};

export type RetrievalEmbeddings = {
  ok: boolean;
  embeddings: {
    configured_backend?: string;
    active_backend?: string;
    semantic_enabled?: boolean;
    vector_kind?: string;
    model?: string;
    model_path?: string;
    package_available?: boolean;
    offline_model_available?: boolean;
    fallback_reason?: string;
    [key: string]: any;
  };
};

export type KnowledgeUpload = {
  id: string;
  filename: string;
  title: string;
  raw_path: string;
  extracted_path: string;
  size: number;
  created_at: string;
  source_url?: string;
  source_type?: string;
  tags?: string[];
  card_id?: string;
  warnings?: string[];
  text_chars?: number;
  import_status?: string;
};

export type KnowledgeDraft = {
  ok: boolean;
  action: string;
  card_id: string;
  title: string;
  source_type: string;
  source_url?: string;
  diff?: string;
  warnings?: string[];
  review_required?: boolean;
  old_hash?: string;
  new_hash?: string;
};

export type KnowledgeCard = {
  id: string;
  title: string;
  path?: string;
  tags?: string[];
  source_type?: string;
  source_url?: string;
  body_hash?: string;
};

export type KnowledgeDirectoryImport = {
  ok: boolean;
  import: {
    ok: boolean;
    root: string;
    namespace: string;
    confirm: boolean;
    scanned_files: number;
    candidates: Array<{
      source_path: string;
      target_path: string;
      action: string;
      card_id: string;
      title: string;
      size: number;
      text_chars?: number;
      warnings?: string[];
    }>;
    summary: {
      candidate_files: number;
      skipped_files: number;
      create: number;
      update: number;
      noop: number;
      imported: number;
      unchanged: number;
      limit_reached?: boolean;
    };
    indexes?: any;
  };
};

export async function ivyeaAgentStatus() {
  const { data } = await api.get<IvyeaAgentStatus>("/ivyea-agent/status");
  return data;
}

export async function ivyeaAgentChat(payload: {
  message: string;
  session_id?: string;
  ops_context?: Record<string, any>;
  max_steps?: number;
  plan_mode?: boolean;
  persist?: boolean;
  inject_retrieval?: boolean;
}) {
  const { data } = await api.post<IvyeaChatResult>("/ivyea-agent/chat", payload, { timeout: 180000 });
  return data;
}

export async function ivyeaAgentChatStream(
  payload: {
    message: string;
    session_id?: string;
    ops_context?: Record<string, any>;
    max_steps?: number;
    plan_mode?: boolean;
    persist?: boolean;
    inject_retrieval?: boolean;
  },
  handlers: {
    onStart?: (data: any) => void;
    onToken?: (text: string) => void;
    onFinal?: (data: any) => void;
    onEvent?: (data: any) => void;
    onError?: (data: any) => void;
  },
) {
  const res = await fetch("/api/ivyea-agent/chat/stream", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok || !res.body) {
    let detail = "";
    try {
      const body = await res.json();
      detail = body.detail || body.error || "";
    } catch {
      detail = await res.text().catch(() => "");
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const emit = (block: string) => {
    let event = "message";
    const dataLines: string[] = [];
    for (const raw of block.split(/\r?\n/)) {
      if (raw.startsWith("event:")) event = raw.slice(6).trim();
      else if (raw.startsWith("data:")) dataLines.push(raw.slice(5).trimStart());
    }
    if (dataLines.length === 0) return;
    let data: any = dataLines.join("\n");
    try { data = JSON.parse(data); } catch { /* keep raw string */ }
    if (event === "start") handlers.onStart?.(data);
    else if (event === "token") handlers.onToken?.(typeof data === "string" ? data : data.text || "");
    else if (event === "final") handlers.onFinal?.(data);
    else if (event === "error") handlers.onError?.(data);
    else handlers.onEvent?.(data);
  };
  while (true) {
    const { value, done } = await reader.read();
    if (value) {
      buffer += decoder.decode(value, { stream: !done });
      let idx = buffer.indexOf("\n\n");
      while (idx >= 0) {
        emit(buffer.slice(0, idx));
        buffer = buffer.slice(idx + 2);
        idx = buffer.indexOf("\n\n");
      }
    }
    if (done) break;
  }
  if (buffer.trim()) emit(buffer);
}

export async function ivyeaChatSessions(limit = 30) {
  const { data } = await api.get<{ ok: boolean; sessions: IvyeaChatSession[] }>("/ivyea-agent/chat/sessions", {
    params: { limit },
  });
  return data;
}

export async function ivyeaChatSession(sessionId: string) {
  const { data } = await api.get<{ ok: boolean; session: IvyeaChatSessionDetail }>(
    `/ivyea-agent/chat/sessions/${encodeURIComponent(sessionId)}`,
  );
  return data;
}

export async function ivyeaRetrievalStatus() {
  const { data } = await api.get<RetrievalStatus>("/ivyea-agent/retrieval/status");
  return data;
}

export async function ivyeaRetrievalEmbeddings() {
  const { data } = await api.get<RetrievalEmbeddings>("/ivyea-agent/retrieval/embeddings");
  return data;
}

export async function ivyeaRetrievalSync() {
  const { data } = await api.post<any>("/ivyea-agent/retrieval/sync", {}, { timeout: 180000 });
  return data;
}

export async function ivyeaKnowledgeFiles(limit = 500) {
  const { data } = await api.get<{
    ok: boolean;
    uploads: { path: string; name: string; size: number; kind: string; mtime: number }[];
    cards: KnowledgeCard[];
    history: KnowledgeUpload[];
  }>("/ivyea-agent/knowledge/files", { params: { limit } });
  return data;
}

export async function ivyeaKnowledgeSearch(q: string, limit = 8) {
  const { data } = await api.get<{ ok: boolean; results: any[] }>("/ivyea-agent/knowledge/search", {
    params: { q, limit },
  });
  return data;
}

export async function ivyeaKnowledgeWatchlist() {
  const { data } = await api.get<{ ok: boolean; summary: any; sources: any[] }>("/ivyea-agent/knowledge/watchlist");
  return data;
}

export async function ivyeaKnowledgeApplyText(params: {
  title: string;
  body: string;
  tags?: string;
  sourceType?: string;
  sourceUrl?: string;
  id?: string;
  rebuild?: boolean;
}) {
  const tags = (params.tags || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const { data } = await api.post<{
    ok: boolean;
    result: {
      applied?: boolean;
      action?: string;
      card?: KnowledgeCard;
      draft?: KnowledgeDraft;
      error?: string;
    };
  }>(
    "/ivyea-agent/knowledge/update/apply",
    {
      id: params.id || "",
      title: params.title,
      body: params.body,
      source_type: params.sourceType || "user",
      source_url: params.sourceUrl || "",
      tags,
      confirm: true,
      rebuild: params.rebuild !== false,
    },
    { timeout: 120000 },
  );
  return data;
}

export async function ivyeaKnowledgeUpload(params: {
  file: File;
  title?: string;
  id?: string;
  sourceUrl?: string;
  sourceType?: string;
  tags?: string;
  confirm?: boolean;
  rebuild?: boolean;
}) {
  const form = new FormData();
  form.append("file", params.file);
  form.append("title", params.title || "");
  form.append("id", params.id || "");
  form.append("source_url", params.sourceUrl || "");
  form.append("source_type", params.sourceType || "user");
  form.append("tags", params.tags || "");
  form.append("confirm", params.confirm ? "true" : "false");
  form.append("rebuild", params.rebuild === false ? "false" : "true");
  const { data } = await api.post<{
    ok: boolean;
    upload: KnowledgeUpload;
    extraction: { text_chars: number; warnings?: string[]; preview?: string };
    draft: KnowledgeDraft;
    apply?: any;
  }>("/ivyea-agent/knowledge/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return data;
}

export async function ivyeaKnowledgeApplyUpload(uploadId: string, confirm = true, rebuild = true) {
  const { data } = await api.post<{
    ok: boolean;
    upload: KnowledgeUpload;
    draft: KnowledgeDraft;
    result: any;
  }>("/ivyea-agent/knowledge/uploads/apply", {
    upload_id: uploadId,
    confirm,
    rebuild,
  });
  return data;
}

export async function ivyeaKnowledgeImportDirectory(params?: {
  root?: string;
  namespace?: string;
  confirm?: boolean;
  rebuild?: boolean;
  maxFiles?: number;
}) {
  const { data } = await api.post<KnowledgeDirectoryImport>(
    "/ivyea-agent/knowledge/import-directory",
    {
      root: params?.root || "",
      namespace: params?.namespace || "gbrain",
      confirm: !!params?.confirm,
      rebuild: params?.rebuild !== false,
      max_files: params?.maxFiles || 1000,
    },
    { timeout: 180000 },
  );
  return data;
}
