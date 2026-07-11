// 后台任务进度条：阶段消息 + 百分比 + 批量计数，跨刷新恢复后同样渲染。
import { Loader2, XCircle } from "lucide-react";
import type { Job } from "./types";

export default function JobProgress({ job, onRetry }: { job: Job | undefined; onRetry?: () => void }) {
  if (!job) return null;
  if (job.status === "failed") {
    return (
      <div className="lst-job lst-job-failed">
        <XCircle size={13} />
        <span className="lst-job-msg">{job.error || "任务失败"}</span>
        {onRetry && <button className="lst-btn" onClick={onRetry}>重试</button>}
      </div>
    );
  }
  if (job.status !== "running") return null;
  const percent = Math.round((job.progress || 0) * 100);
  return (
    <div className="lst-job">
      <Loader2 size={13} className="spin" />
      <div className="lst-job-body">
        <div className="lst-job-line">
          <span className="lst-job-msg">{job.message || "运行中…"}</span>
          <span className="lst-job-pct">
            {job.total > 0 ? `${job.done_count}/${job.total} · ` : ""}{percent}%
          </span>
        </div>
        <div className="lst-job-bar"><i style={{ width: `${Math.max(3, percent)}%` }} /></div>
      </div>
    </div>
  );
}
