// 轻量 toast：右下角堆叠、自动消退、按语气着色。
// 从 listing 工作台的 toast 提炼为工作台通用版（样式 .wb-toast* 在 workbench.css）。
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";

export type ToastTone = "success" | "warn" | "error" | "info";

interface ToastItem {
  id: number;
  tone: ToastTone;
  text: string;
  leaving?: boolean;
}

type NotifyFn = (tone: ToastTone, text: string) => void;

const ToastContext = createContext<NotifyFn>(() => {});

export function useToast(): NotifyFn {
  return useContext(ToastContext);
}

const ICONS: Record<ToastTone, ReactNode> = {
  success: <CheckCircle2 size={14} />,
  warn: <AlertTriangle size={14} />,
  error: <XCircle size={14} />,
  info: <Info size={14} />,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.map((item) => (item.id === id ? { ...item, leaving: true } : item)));
    setTimeout(() => setItems((prev) => prev.filter((item) => item.id !== id)), 220);
  }, []);

  const notify = useCallback<NotifyFn>((tone, text) => {
    const id = nextId.current++;
    setItems((prev) => [...prev.slice(-4), { id, tone, text }]);
    // 错误多留一会儿，成功快速让路
    const ttl = tone === "error" ? 8000 : tone === "warn" ? 6000 : 3500;
    setTimeout(() => dismiss(id), ttl);
  }, [dismiss]);

  const value = useMemo(() => notify, [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="wb-toasts" role="status" aria-live="polite">
        {items.map((item) => (
          <div key={item.id}
            className={`wb-toast wb-toast-${item.tone}${item.leaving ? " leaving" : ""}`}
            onClick={() => dismiss(item.id)}>
            {ICONS[item.tone]}
            <span>{item.text}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
