import { useEffect, useId, useRef, useState } from 'react';
import { type WordLesson } from '../domain/word-practice';

export function WordCoursePicker({
  lesson,
  lessons,
  onSelect,
  onListen,
}: {
  lesson: WordLesson;
  lessons: WordLesson[];
  onSelect: (id: string) => void;
  onListen: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [unit, setUnit] = useState(lesson.unit);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const element = dialog.current!;
    element.showModal();
    const returnFocus = trigger.current;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    element
      .querySelector<HTMLButtonElement>('[aria-current="true"]')
      ?.focus({ preventScroll: true });
    return () => {
      element.close();
      document.body.style.overflow = previous;
      returnFocus?.focus({ preventScroll: true });
    };
  }, [open]);
  return (
    <>
      <button
        className="word-course-trigger"
        ref={trigger}
        aria-label={`选择课程，当前${lesson.title}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          setUnit(lesson.unit);
          setOpen(true);
        }}
      >
        <span>
          第{lesson.unit}单元 · {lesson.unitTitle}
        </span>
        <strong>
          {lesson.title}
          <span aria-hidden="true">⌄</span>
        </strong>
      </button>
      <dialog
        ref={dialog}
        className="word-course-dialog"
        aria-labelledby={titleId}
        onCancel={(event) => {
          event.preventDefault();
          setOpen(false);
        }}
        onClick={(event) => {
          if (event.target === event.currentTarget) {
            const bounds = event.currentTarget.getBoundingClientRect();
            if (
              event.clientX < bounds.left ||
              event.clientX > bounds.right ||
              event.clientY < bounds.top ||
              event.clientY > bounds.bottom
            )
              setOpen(false);
          }
        }}
      >
        <header>
          <div>
            <h2 id={titleId}>选择课程</h2>
            <p>按教材单元找一找，点课名进入。</p>
          </div>
          <button aria-label="关闭选课" onClick={() => setOpen(false)}>
            ✕
          </button>
        </header>
        <nav className="word-unit-tabs" aria-label="教材单元">
          {Array.from(new Set(lessons.map((item) => item.unit))).map((value) => (
            <button key={value} aria-pressed={value === unit} onClick={() => setUnit(value)}>
              第{value}单元
            </button>
          ))}
        </nav>
        <div className="word-course-list">
          <h3>{lessons.find((item) => item.unit === unit)!.unitTitle}</h3>
          <div className="word-course-options">
            {lessons
              .filter((item) => item.unit === unit)
              .map((item) => (
                <div className="word-course-option" key={item.id}>
                  <button
                    aria-label={`选择${item.title}${item.id === lesson.id ? '，当前课' : ''}`}
                    aria-current={item.id === lesson.id ? 'true' : undefined}
                    onClick={() => {
                      onSelect(item.id);
                      setOpen(false);
                    }}
                  >
                    <span>{lessons.indexOf(item) + 1}</span>
                    <strong>{item.title}</strong>
                    {item.id === lesson.id && <small>当前课</small>}
                  </button>
                  <button
                    className="word-course-listen"
                    aria-label={`听课名${item.title}`}
                    onClick={() => onListen(item.audioId)}
                  >
                    🔊
                  </button>
                </div>
              ))}
          </div>
        </div>
      </dialog>
    </>
  );
}
