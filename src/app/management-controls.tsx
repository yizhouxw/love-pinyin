import { useEffect, useRef } from 'react';

export function ReducedMotionControl({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="setting-toggle">
      <input
        type="checkbox"
        aria-label="减少动态效果"
        checked={checked}
        disabled={disabled}
        onChange={(event) => {
          const next = event.currentTarget.checked;
          onChange(next);
        }}
      />
      开启
    </label>
  );
}

export function AdultConfirmDialog({
  open,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  return (
    <dialog
      className="adult-confirm-dialog"
      ref={dialog}
      aria-labelledby="adult-confirm-title"
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      <span className="eyebrow">请家长接手</span>
      <h2 id="adult-confirm-title">这里是家庭管理区</h2>
      <p>
        这里会显示学习记录，并提供设备配对、备份和删除操作。请把设备交给家长再继续。
        这一步只用于防止孩子误触，不会代替家长权限验证。
      </p>
      <div className="adult-confirm-actions">
        <button className="quiet" onClick={onCancel}>
          返回孩子学习
        </button>
        <button autoFocus onClick={onConfirm}>
          我是家长，继续
        </button>
      </div>
    </dialog>
  );
}
