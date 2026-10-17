import type { Lesson, Progress } from '../domain/learning-api';
export function LessonNavigation({
  lessons,
  currentLesson,
  masteryById,
  onSelect,
}: {
  lessons: Lesson[];
  currentLesson: Lesson | undefined;
  masteryById: Map<string, Progress['mastery'][number]>;
  onSelect: (id: string) => void;
}) {
  return (
    <section className="map-card lesson-navigation" aria-label="学习路线">
      <div className="section-heading">
        <div>
          <span className="eyebrow">学习路线</span>
          <h2>一步一步，点亮拼音</h2>
        </div>
        <span className="map-count">{lessons.length} 课</span>
      </div>
      <div className="lesson-grid">
        {lessons.map((lesson) => {
          const future = !currentLesson || lesson.order > currentLesson.order;
          const lessonMastery = (lesson.knowledgeIds as string[])
            .map((id) => masteryById.get(id))
            .filter((item) => item !== undefined);
          const dueCount = lessonMastery.filter((item) => item.reviewDue).length;
          const masteredCount = lessonMastery.filter((item) => item.status === 'mastered').length;
          const practiced = lessonMastery.some(
            (item) => item.sampleSize > 0 || item.status !== 'not-started',
          );
          const progressLabel =
            lessonMastery.length > 0 && masteredCount === lessonMastery.length
              ? '已掌握'
              : practiced
                ? '练习中'
                : '未开始';
          return (
            <button
              key={lesson.id}
              className={`lesson-tile ${lesson.id === currentLesson?.id ? 'selected' : ''} ${future ? 'locked' : ''}`}
              onClick={() => onSelect(lesson.id)}
            >
              <span className="tile-number">{String(lesson.order).padStart(2, '0')}</span>
              <strong>{lesson.title}</strong>
              <small>
                {future
                  ? '后续课程 · 可预览'
                  : `${lesson.order === currentLesson?.order ? '正在学习 · ' : ''}${progressLabel}`}
              </small>
              {dueCount > 0 && <span className="review-due-badge">到期复习 · {dueCount} 项</span>}
            </button>
          );
        })}
      </div>
    </section>
  );
}
