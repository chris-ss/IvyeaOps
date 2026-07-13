// 小并发池：把一批任务限制在 limit 个并发内执行（用于"全部刷新"这类
// 每项都消耗数据源配额的批量请求，避免瞬间打满上游限流）。
// worker 内部自行处理错误（首页各卡片本就 per-item 捕获并展示错误态）。
export async function runPool<T>(
  items: readonly T[],
  worker: (item: T) => Promise<unknown>,
  limit = 3,
): Promise<void> {
  let next = 0;
  const lane = async () => {
    while (next < items.length) {
      const item = items[next++];
      try { await worker(item); } catch { /* per-item errors handled by worker */ }
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, lane));
}
