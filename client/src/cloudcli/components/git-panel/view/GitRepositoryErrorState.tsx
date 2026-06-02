import { GitBranch } from 'lucide-react';

type GitRepositoryErrorStateProps = {
  error: string;
  details?: string;
};

// 后端 git 错误文案是英文,这里做常见短语本地化
const zh = (s?: string): string => (s || '')
  .replace(/Git operation failed/gi, 'Git 操作失败')
  .replace(/Failed to get git status:?/gi, '获取 Git 状态失败：')
  .replace(/Not a git repository\.?/gi, '不是 Git 仓库。')
  .replace(/This directory does not contain a \.git folder\.?/gi, '此目录没有 .git 文件夹。')
  .replace(/Initialize a git repository with ["'`]?git init["'`]? to use source control features\.?/gi, '可运行 git init 初始化仓库以启用版本控制。');

export default function GitRepositoryErrorState({ error, details }: GitRepositoryErrorStateProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 py-12 text-muted-foreground">
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/50">
        <GitBranch className="h-8 w-8 opacity-40" />
      </div>
      <h3 className="mb-3 text-center text-lg font-medium text-foreground">{zh(error)}</h3>
      {details && (
        <p className="mb-6 max-w-md text-center text-sm leading-relaxed">{zh(details)}</p>
      )}
      <div className="max-w-md rounded-xl border border-primary/10 bg-primary/5 p-4">
        <p className="text-center text-sm text-primary">
          <strong>提示：</strong>在项目目录运行{' '}
          <code className="rounded-md bg-primary/10 px-2 py-1 font-mono text-xs">git init</code>{' '}
          即可初始化 Git 版本控制。
        </p>
      </div>
    </div>
  );
}
