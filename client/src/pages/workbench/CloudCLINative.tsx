// claudecodeui 原生移植的 ops 包裹页。
//
// 关键:cloudcli 用**独立的 React root**(createRoot)挂到 #ccui-root DOM 节点,
// 从而脱离 ops 的 React 树 —— 不继承 ops 的 BrowserRouter / 各 context,
// cloudcli 自己的 MemoryRouter 成为顶层 Router,避免 "nested <Router>" invariant。
// 仍是同一页面、同一 JS bundle、同一份(作用域化的)CSS —— 不是 iframe。
import { useEffect, useRef, Component, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import CloudCLIApp from '../../cloudcli/App';
import { applyOpsHubTheme } from '../../cloudcli/utils/opsHubTheme';
import '../../cloudcli/index.css';

class CcuiBoundary extends Component<{ children: ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) { return { err }; }
  componentDidCatch(err: Error) { console.error('[CloudCLI render error]', err); }
  render() {
    if (this.state.err) {
      return (
        <pre style={{ padding: 16, margin: 0, color: '#ff9090', whiteSpace: 'pre-wrap', fontSize: 12, lineHeight: 1.5, overflow: 'auto', height: '100%', fontFamily: 'monospace' }}>
          {'CloudCLI 渲染错误:\n\n' + this.state.err.message + '\n\n' + (this.state.err.stack || '')}
        </pre>
      );
    }
    return this.props.children;
  }
}

export default function CloudCLINative() {
  const hostRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<Root | null>(null);

  useEffect(() => {
    if (!hostRef.current) return;
    const host = hostRef.current;

    // 主题:初始注入 ops 当前主题,并监听 ops 主题切换 —— 注入到 #ccui-root 容器
    const syncTheme = () => {
      const theme = localStorage.getItem('opshub.theme') || 'dark';
      applyOpsHubTheme(theme, host);
    };
    syncTheme();
    const onThemeChange = (e: Event) => {
      const t = (e as CustomEvent<string>).detail;
      applyOpsHubTheme(typeof t === 'string' ? t : (localStorage.getItem('opshub.theme') || 'dark'), host);
    };
    window.addEventListener('opshub:theme-changed', onThemeChange);

    if (!rootRef.current) {
      rootRef.current = createRoot(host);
    }
    rootRef.current.render(
      <CcuiBoundary>
        <CloudCLIApp />
      </CcuiBoundary>,
    );
    return () => {
      window.removeEventListener('opshub:theme-changed', onThemeChange);
      const r = rootRef.current;
      rootRef.current = null;
      setTimeout(() => r?.unmount(), 0);
    };
  }, []);

  return (
    <div
      id="ccui-root"
      ref={hostRef}
      style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden', transform: 'translateZ(0)' }}
    />
  );
}
