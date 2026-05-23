import { useState, useCallback, createContext, useContext } from "react";

type ConfirmOptions = { title?: string; message: string; confirmText?: string; cancelText?: string; danger?: boolean };
type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn>(() => Promise.resolve(false));

export function useConfirm() {
  return useContext(ConfirmContext);
}

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<(ConfirmOptions & { resolve: (v: boolean) => void }) | null>(null);

  const confirm: ConfirmFn = useCallback((opts) => {
    return new Promise<boolean>((resolve) => setState({ ...opts, resolve }));
  }, []);

  const close = (result: boolean) => { state?.resolve(result); setState(null); };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {state && (
        <div className="confirm-bd" onClick={() => close(false)}>
          <div className="confirm-card" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-body">
              <div className={`confirm-icon-ring ${state.danger ? "danger" : "normal"}`}>
                {state.danger ? "🗑" : "?"}
              </div>
              {state.title && <div className="confirm-title">{state.title}</div>}
              <div className="confirm-msg">{state.message}</div>
            </div>
            <div className="confirm-foot">
              <button className="tbtn" onClick={() => close(false)}>{state.cancelText || "取消"}</button>
              <button
                className={`tbtn ${state.danger ? "confirm-ok-danger" : "confirm-ok-normal"}`}
                onClick={() => close(true)}
              >
                {state.confirmText || "确认"}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}
