import { type ReactNode, useEffect, useId, useRef, useState } from 'react';

export function PracticeCoursePicker({
  label,
  title,
  instruction,
  subtitle,
  selected,
  onOpenChange,
  children,
}: {
  label: string;
  title: string;
  instruction: string;
  subtitle: string;
  selected: string;
  onOpenChange?: (open: boolean) => void;
  children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const element = dialog.current!;
    const returnFocus = trigger.current;
    const previous = document.body.style.overflow;
    element.showModal();
    document.body.style.overflow = 'hidden';
    const current = element.querySelector<HTMLButtonElement>('[aria-current="true"]');
    current?.focus({ preventScroll: true });
    current?.scrollIntoView({ block: 'nearest' });
    return () => {
      element.close();
      document.body.style.overflow = previous;
      returnFocus?.focus({ preventScroll: true });
    };
  }, [open]);
  const close = () => {
    setOpen(false);
    onOpenChange?.(false);
  };

  return (
    <>
      <button
        className="word-course-trigger"
        ref={trigger}
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          onOpenChange?.(true);
          setOpen(true);
        }}
      >
        <span>{subtitle}</span>
        <strong>
          {selected} <span aria-hidden="true">⌄</span>
        </strong>
      </button>
      <dialog
        ref={dialog}
        className="word-course-dialog"
        aria-labelledby={titleId}
        onCancel={(event) => {
          event.preventDefault();
          close();
        }}
        onClick={(event) => {
          if (event.target !== event.currentTarget) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          if (
            event.clientX < bounds.left ||
            event.clientX > bounds.right ||
            event.clientY < bounds.top ||
            event.clientY > bounds.bottom
          ) {
            close();
          }
        }}
      >
        <header>
          <div>
            <h2 id={titleId}>{title}</h2>
            <p>{instruction}</p>
          </div>
          <button aria-label="关闭选课" onClick={close}>
            ✕
          </button>
        </header>
        {children(close)}
      </dialog>
    </>
  );
}
