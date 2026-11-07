import type { Lesson, Progress } from '../domain/learning-api';
import { api } from '../platform/api-client';

export function IOSClassroomSettings({
  lessons,
  progress,
  lessonChoice,
  setLessonChoice,
  busy,
  act,
  refresh,
}: {
  lessons: Lesson[];
  progress: Progress;
  lessonChoice: string;
  setLessonChoice: (value: string) => void;
  busy: boolean;
  act: (work: () => Promise<void>) => Promise<void>;
  refresh: () => Promise<void>;
}) {
  return (
    <section className="map-card" aria-label="此设备学习设置">
      <h2>当前学习课</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void act(async () => {
            await api('/household/current-lesson', {
              method: 'PUT',
              body: JSON.stringify({ lessonId: lessonChoice, expectedRevision: progress.revision }),
            });
            await refresh();
          });
        }}
      >
        <label>
          学校正在学习的课程
          <select value={lessonChoice} onChange={(event) => setLessonChoice(event.target.value)}>
            <option value="" disabled>
              请选择课程
            </option>
            {lessons.map((lesson) => (
              <option key={lesson.id} value={lesson.id}>
                第 {lesson.order} 课 · {lesson.title}
              </option>
            ))}
          </select>
        </label>
        <button disabled={busy || !lessonChoice || lessonChoice === progress.selectedLessonId}>
          保存当前课
        </button>
      </form>
      <h2>此设备学习记录</h2>
      <p>
        已作答 {progress.attemptCount ?? 0} 题，完成 {progress.completedSessions} 轮练习。
      </p>
      <p>记录保存在此设备。请保留 App，备份入口将在后续版本提供。</p>
    </section>
  );
}
