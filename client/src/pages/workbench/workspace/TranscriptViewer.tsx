import { useEffect, useState } from "react";
import {
  getSessionTranscript,
  resumeExternalSession,
  type Project,
  type ProjectSession,
  type TranscriptMessage,
} from "../../../api/projects";

type Props = {
  project: Project;
  projectSession: ProjectSession;
  /** Called after a successful resume; the parent should switch selection
   * to the new hub session id (which has `source=hub`). */
  onResumed: (newHubSessionId: string) => void;
};

/**
 * Read-only viewer for an external Claude/Codex jsonl session.
 *
 * Shows:
 *   – header: meta + 「继续会话」action (calls /resume, returns a new
 *     hub session id, parent switches selection to it)
 *   – scrolling transcript: user/assistant/system bubbles with embedded
 *     tool calls / results inlined
 *
 * Backend already trimmed noise (slash-command bookkeeping for Claude,
 * environment_context wrappers for Codex) so we just render what we get.
 */
export default function TranscriptViewer({ project, projectSession, onResumed }: Props) {
  const [messages, setMessages] = useState<TranscriptMessage[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [resuming, setResuming] = useState(false);
  const [resumeErr, setResumeErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setErr(null);
    setMessages(null);
    getSessionTranscript(project.id, projectSession.id)
      .then((r) => { if (alive) setMessages(r.messages); })
      .catch((e: any) => {
        if (alive) setErr(e?.response?.data?.detail || e?.message || "加载 transcript 失败");
      })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [project.id, projectSession.id]);

  const handleResume = async () => {
    if (resuming) return;
    setResuming(true);
    setResumeErr(null);
    try {
      const r = await resumeExternalSession(project.id, projectSession.id);
      onResumed(r.session_id);
    } catch (e: any) {
      setResumeErr(e?.response?.data?.detail || e?.message || "继续会话失败");
    } finally {
      setResuming(false);
    }
  };

  return (
    <div className="ws-transcript">
      <div className="ws-transcript-head">
        <div className="ws-transcript-meta">
          <span className={"ws-src-chip src-" + projectSession.source}>
            {projectSession.source}
          </span>
          <span className="ws-transcript-title" title={projectSession.title}>{projectSession.title}</span>
          <span className="ws-transcript-id" title={projectSession.id}>{projectSession.id.slice(0, 12)}…</span>
        </div>
        <button
          className="tbtn tbtn-acc"
          onClick={handleResume}
          disabled={resuming}
          title="启动 PTY，--resume 加载该会话的历史上下文，生成新的 hub 会话继续聊"
        >
          {resuming ? "继续中…" : "↻ 继续会话"}
        </button>
      </div>
      {resumeErr && (
        <div className="ws-transcript-err">⚠ {resumeErr}</div>
      )}

      <div className="ws-transcript-body">
        {loading && <div className="ws-transcript-info">加载 transcript 中…</div>}
        {err && <div className="ws-transcript-err">⚠ {err}</div>}
        {!loading && !err && messages && messages.length === 0 && (
          <div className="ws-transcript-info">该会话没有可显示的消息</div>
        )}
        {messages && messages.length > 0 && (
          <>
            <MessageList messages={messages} />
            <div className="ws-transcript-foot">共 {messages.length} 条消息 · 该视图只读</div>
          </>
        )}
      </div>
    </div>
  );
}

function MessageList({ messages }: { messages: TranscriptMessage[] }) {
  return (
    <div className="ws-tr-list">
      {messages.map((m, i) => (
        <MessageBubble key={i} msg={m} />
      ))}
    </div>
  );
}

function MessageBubble({ msg }: { msg: TranscriptMessage }) {
  const isTool = msg.kind === "tool_call" || msg.kind === "tool_result";
  const cls = "ws-tr-msg ws-tr-" + msg.role + (isTool ? " ws-tr-tool" : "");
  const label =
    msg.role === "user" ? "用户" :
    msg.role === "assistant" ? "AI" :
    msg.role === "system" ? "系统" : msg.role;
  return (
    <div className={cls}>
      <div className="ws-tr-msg-head">
        <span className="ws-tr-msg-role">{label}</span>
        {msg.ts && <span className="ws-tr-msg-ts">{formatTs(msg.ts)}</span>}
        {isTool && <span className="ws-tr-msg-kind">{msg.kind === "tool_call" ? "调用" : "结果"}</span>}
      </div>
      <pre className="ws-tr-msg-body">{msg.text}</pre>
    </div>
  );
}

function formatTs(ts: string | null): string {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleString("zh-CN", { hour12: false, year: "2-digit", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch {
    return ts;
  }
}
