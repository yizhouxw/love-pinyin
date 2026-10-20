import { useEffect, useId, useRef, useState } from 'react';
import type { DailyItem } from '../domain/daily-reading';
import { isGuest } from '../platform/guest';
import { PlaybackGapControl } from './playback-gap-control';

export function QuickGapSettings({
  seconds,
  item,
  onSave,
  disabled = false,
}: {
  seconds: number;
  item?: DailyItem;
  onSave: (seconds: number) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const backdropPress = useRef(false);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (!open) {
      if (element.open) {
        element.close();
        trigger.current?.focus({ preventScroll: true });
      }
      return;
    }
    if (!element.open) element.showModal();
    const previousOverflow = document.body.style.overflow;
    const previousRootOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
      document.documentElement.style.overflow = previousRootOverflow;
    };
  }, [open]);
  return (
    <div className="daily-gap-settings">
      <button
        ref={trigger}
        className="daily-gap-trigger"
        type="button"
        tabIndex={0}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`间隔设置，基础间隔${seconds.toFixed(1)}秒`}
        onClick={() => setOpen(true)}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="8.5" />
          <path d="M12 7v5l3 2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span>间隔</span>
        <strong>
          {seconds.toFixed(1)}
          <span> 秒</span>
        </strong>
        <svg
          className="gap-chevron"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          aria-hidden="true"
        >
          <path d="m6 4 4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <dialog
        ref={dialog}
        className="gap-dialog"
        aria-labelledby={titleId}
        onCancel={(event) => {
          event.preventDefault();
          setOpen(false);
        }}
        onPointerDown={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect();
          backdropPress.current =
            event.target === event.currentTarget &&
            (event.clientX < bounds.left ||
              event.clientX > bounds.right ||
              event.clientY < bounds.top ||
              event.clientY > bounds.bottom);
        }}
        onClick={(event) => {
          if (event.target !== event.currentTarget || !backdropPress.current) return;
          backdropPress.current = false;
          const bounds = event.currentTarget.getBoundingClientRect();
          if (
            event.clientX < bounds.left ||
            event.clientX > bounds.right ||
            event.clientY < bounds.top ||
            event.clientY > bounds.bottom
          )
            setOpen(false);
        }}
      >
        <header className="gap-dialog-heading">
          <div>
            <h2 id={titleId}>跟读间隔</h2>
            <p>选一个舒服的节奏，慢慢读。</p>
          </div>
          <button
            type="button"
            className="gap-close"
            tabIndex={0}
            aria-label="关闭间隔设置"
            autoFocus
            onClick={() => setOpen(false)}
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              aria-hidden="true"
            >
              <path d="m7 7 10 10M17 7 7 17" strokeLinecap="round" />
            </svg>
          </button>
        </header>
        {open && (
          <PlaybackGapControl
            key={seconds}
            seconds={seconds}
            disabled={disabled}
            item={item}
            onSave={(value) => {
              onSave(value);
              setOpen(false);
            }}
            onCancel={() => setOpen(false)}
            deviceOnly
            guest={isGuest()}
          />
        )}
      </dialog>
    </div>
  );
}
