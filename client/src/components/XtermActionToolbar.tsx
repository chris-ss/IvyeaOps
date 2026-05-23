import { useEffect, useState } from "react";

type Props = {
  selectMode: boolean;
  mobileMode?: boolean;
  onToggleSelectMode: () => void;
  onCopySelection: () => void;
  onCopyVisible: () => void;
  onPaste: () => void;
  onSendShortcut?: (data: string) => void;
  extra?: React.ReactNode;
};

export default function XtermActionToolbar({
  selectMode,
  mobileMode = false,
  onToggleSelectMode,
  onCopySelection,
  onCopyVisible,
  onPaste,
  onSendShortcut,
  extra,
}: Props) {
  const [mobilePanel, setMobilePanel] = useState<"copy" | "keys" | null>(null);

  useEffect(() => {
    if (!mobileMode) setMobilePanel(null);
  }, [mobileMode]);

  if (!mobileMode) {
    return (
      <div className="xterm-action-row">
        <button
          className={"tbtn xterm-select-toggle" + (selectMode ? " active" : "")}
          onClick={onToggleSelectMode}
          title={selectMode ? "退出复制模式，恢复正常输入" : "进入复制模式，避免拖拽/长按把事件送进终端"}
        >
          {selectMode ? "退出复制" : "复制模式"}
        </button>
        <button className="tbtn" onClick={onCopySelection} title="复制当前选中的文本（浏览器选区或 xterm 选区）">
          复制选中
        </button>
        <button className="tbtn" onClick={onCopyVisible} title="复制当前屏幕可见内容，适合作为手机端兜底">
          复制屏幕
        </button>
        <button className="tbtn" onClick={onPaste} title="从系统剪贴板粘贴到终端">
          粘贴
        </button>
        {extra}
      </div>
    );
  }

  return (
    <div className="xterm-mobile-tools">
      <div className="xterm-action-row mobile-primary">
        <button
          className={"tbtn xterm-group-toggle" + (mobilePanel === "copy" ? " active" : "")}
          onClick={() => setMobilePanel((prev) => (prev === "copy" ? null : "copy"))}
        >
          复制
        </button>
        <button className="tbtn" onClick={onPaste} title="从系统剪贴板粘贴到终端">
          粘贴
        </button>
        <button
          className={"tbtn xterm-group-toggle" + (mobilePanel === "keys" ? " active" : "")}
          onClick={() => setMobilePanel((prev) => (prev === "keys" ? null : "keys"))}
        >
          快捷键
        </button>
        {extra}
      </div>

      {mobilePanel === "copy" && (
        <div className="xterm-mobile-panel">
          <button
            className={"tbtn xterm-select-toggle" + (selectMode ? " active" : "")}
            onClick={onToggleSelectMode}
            title={selectMode ? "退出复制模式，恢复正常输入" : "进入复制模式，避免拖拽/长按把事件送进终端"}
          >
            {selectMode ? "退出复制模式" : "进入复制模式"}
          </button>
          <button className="tbtn" onClick={onCopySelection}>复制选中</button>
          <button className="tbtn" onClick={onCopyVisible}>复制屏幕</button>
        </div>
      )}

      {mobilePanel === "keys" && onSendShortcut && (
        <div className="xterm-mobile-shortcuts">
          <button className="tbtn" onClick={() => onSendShortcut("\u001b")}>Esc</button>
          <button className="tbtn" onClick={() => onSendShortcut("\t")}>Tab</button>
          <button className="tbtn" onClick={() => onSendShortcut("\u0003")}>Ctrl+C</button>
          <button className="tbtn" onClick={() => onSendShortcut("\u001b[A")}>↑</button>
          <button className="tbtn" onClick={() => onSendShortcut("\u001b[B")}>↓</button>
          <button className="tbtn" onClick={() => onSendShortcut("\u001b[D")}>←</button>
          <button className="tbtn" onClick={() => onSendShortcut("\u001b[C")}>→</button>
          <button className="tbtn" onClick={() => onSendShortcut("\r")}>Enter</button>
        </div>
      )}
    </div>
  );
}
