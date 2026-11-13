import { createContext, useEffect, useRef, type ReactNode } from 'react';

export const InQuickSettings = createContext(false);

/** A local settings panel: changes retain their existing save semantics. */
export function QuickSettings({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const position = () => {
      const details = ref.current;
      const panel = details?.querySelector<HTMLElement>('.quick-settings-panel');
      if (!details?.open || !panel) return;
      panel.style.removeProperty('top');
      panel.style.removeProperty('bottom');
      panel.style.removeProperty('max-height');
      panel.style.removeProperty('inset-inline-start');
      if (innerWidth <= 600 || innerHeight <= 500) return;
      const anchor = details.getBoundingClientRect();
      const below = innerHeight - anchor.bottom;
      const above = anchor.top;
      const upward = below < panel.scrollHeight + 24 && above > below;
      panel.style.maxHeight = `${Math.max(100, (upward ? above : below) - 24)}px`;
      if (upward) {
        panel.style.top = 'auto';
        panel.style.bottom = 'calc(100% + 8px)';
      }
      const width = panel.getBoundingClientRect().width;
      panel.style.insetInlineStart = `${Math.max(12 - anchor.left, Math.min(0, innerWidth - anchor.left - width - 12))}px`;
    };
    const details = ref.current;
    details?.addEventListener('toggle', position);
    window.addEventListener('resize', position);
    return () => {
      details?.removeEventListener('toggle', position);
      window.removeEventListener('resize', position);
    };
  }, []);
  useEffect(() => {
    const close = (event: KeyboardEvent | PointerEvent) => {
      const panel = ref.current;
      if (!panel?.open) return;
      if (event instanceof KeyboardEvent) {
        if (event.key !== 'Escape') return;
        event.preventDefault();
        panel.open = false;
        panel.querySelector('summary')?.focus();
      } else if (event.target instanceof Node && !panel.contains(event.target)) {
        panel.open = false;
      }
    };
    document.addEventListener('keydown', close);
    document.addEventListener('pointerdown', close);
    return () => {
      document.removeEventListener('keydown', close);
      document.removeEventListener('pointerdown', close);
    };
  }, []);
  return (
    <details ref={ref} name="local-quick-settings" className={`quick-settings ${className}`}>
      <InQuickSettings.Provider value={true}>{children}</InQuickSettings.Provider>
    </details>
  );
}

export function CloseQuickSettings() {
  return (
    <button
      type="button"
      className="quick-settings-done"
      onClick={(event) => {
        const panel = event.currentTarget.closest('details');
        if (!panel) return;
        panel.open = false;
        panel.querySelector('summary')?.focus({ preventScroll: true });
      }}
    >
      完成
    </button>
  );
}
