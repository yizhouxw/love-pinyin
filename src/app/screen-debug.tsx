import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const screens = {
  phone: { label: '手机', width: 390, height: 844 },
  small: { label: '小屏手机', width: 320, height: 568 },
  desktop: { label: '桌面', width: 1280, height: 800 },
};

export function ScreenDebug({ onClose }: { onClose: () => void }) {
  const modal = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const close = () => {
    modal.current?.close();
    setOpen(false);
    opener.current?.focus();
    onClose();
  };
  const [open, setOpen] = useState(false);
  const [screen, setScreen] = useState<keyof typeof screens>('phone');
  const [landscape, setLandscape] = useState(false);
  if (window.self !== window.top) return null;
  const size = screens[screen];
  const width = landscape ? size.height : size.width;
  const height = landscape ? size.width : size.height;
  return (
    <div className="parent-setting">
      <div>
        <strong>Web 屏幕交互调试</strong>
        <p>预览不同屏幕尺寸；操作会保存到当前家庭档案。原生能力与真机仍需单独验证。</p>
      </div>
      <button ref={opener} onClick={() => setOpen(true)}>
        打开屏幕调试
      </button>
      {open &&
        createPortal(
          <dialog
            ref={(node) => {
              modal.current = node;
              if (node && !node.open) node.showModal();
            }}
            onCancel={close}
            className="screen-debug"
            role="dialog"
            aria-modal="true"
            aria-label="Web 屏幕交互调试"
          >
            <header>
              <select
                aria-label="预览屏幕"
                value={screen}
                onChange={(event) => setScreen(event.target.value as keyof typeof screens)}
              >
                {Object.entries(screens).map(([key, item]) => (
                  <option key={key} value={key}>
                    {item.label}
                  </option>
                ))}
              </select>
              <button onClick={() => setLandscape(!landscape)}>切换横竖屏</button>
              <span>
                {width} × {height} CSS px
              </span>
              <button autoFocus onClick={close}>
                关闭调试
              </button>
            </header>
            <p>真实 Web 页面 · 操作会保存 · 不模拟原生能力</p>
            <div className="screen-debug-scroll">
              <iframe
                title="屏幕交互预览"
                src={window.location.pathname}
                style={{ width, height }}
              />
            </div>
          </dialog>,
          document.body,
        )}
    </div>
  );
}
