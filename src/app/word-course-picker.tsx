import { useState } from 'react';
import { type WordLesson } from '../domain/word-practice';
import { PracticeCoursePicker } from './practice-course-picker';

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
  const [unit, setUnit] = useState(lesson.unit);
  return (
    <PracticeCoursePicker
      label={`选择课程，当前${lesson.title}`}
      title="选择课程"
      instruction="按教材单元找一找，点课名进入。"
      subtitle={`第${lesson.unit}单元 · ${lesson.unitTitle}`}
      selected={lesson.title}
      onOpenChange={(open) => {
        if (open) setUnit(lesson.unit);
      }}
    >
      {(close) => (
        <>
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
                        close();
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
        </>
      )}
    </PracticeCoursePicker>
  );
}
