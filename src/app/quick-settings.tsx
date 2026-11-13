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

export function ContextHelp({ children, label = '帮助' }: { children: ReactNode; label?: string }) {
  return (
    <QuickSettings className="context-help">
      <summary aria-label={label}>
        <span aria-hidden="true">ⓘ</span>
        <span>帮助</span>
      </summary>
      <div className="quick-settings-panel">
        <div className="context-help-heading">
          <strong>{label}</strong>
          <CloseQuickSettings />
        </div>
        {children}
      </div>
    </QuickSettings>
  );
}

export function SettingsGlyph() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      aria-hidden="true"
    >
      <path d="M3 6h6m6 0h6M3 12h12m6 0h0M3 18h2m6 0h10" strokeLinecap="round" />
      <circle cx="12" cy="6" r="3" />
      <circle cx="18" cy="12" r="3" />
      <circle cx="8" cy="18" r="3" />
    </svg>
  );
}
