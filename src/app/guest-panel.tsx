import type { LearningSettingsProps } from './settings-types';
import playback from '../../content/playback.json';
import type { Lesson } from '../domain/learning-api';
import { api } from '../platform/api-client';
import { ReducedMotionControl } from './management-controls';
import { PlaybackGapControl } from './playback-gap-control';

export function GuestPanel({
  curriculum,
  progress,
  lessonChoice,
  setLessonChoice,
  busy,
  refresh,
  act,
}: LearningSettingsProps) {
  return (
    <section className="parent-panel guest-settings">
      <h2>访客学习设置</h2>
      <p>
        {progress.attemptCount ?? 0} 次临时练习记录 · {progress.completedSessions} 轮练习
      </p>
      <p>
        进度只缓存在当前标签页。关闭标签页通常会清除；浏览器恢复会话可能恢复缓存，使用“清除并退出访客”可主动清除。不会合并到家庭档案。
      </p>
      <label htmlFor="guest-lesson">当前学习课</label>
      <p role="status">
        当前练习：第{' '}
        {
          curriculum.lessons.find((lesson: Lesson) => lesson.id === progress.selectedLessonId)
            ?.order
        }{' '}
        课
      </p>
      <select
        id="guest-lesson"
        disabled={busy}
        value={lessonChoice}
        onChange={(event) => setLessonChoice(event.target.value)}
      >
        {curriculum.lessons.map((lesson: Lesson) => (
          <option key={lesson.id} value={lesson.id}>
            {lesson.order}. {lesson.title}
          </option>
        ))}
      </select>
      <button
        className="quiet"
        disabled={busy || !lessonChoice}
        onClick={() =>
          void act(async () => {
            await api('/household/current-lesson', {
              method: 'PUT',
              body: JSON.stringify({ lessonId: lessonChoice, expectedRevision: progress.revision }),
            });
            await refresh();
          })
        }
      >
        应用到访客练习
      </button>
      <PlaybackGapControl
        guest
        key={progress.settings.playbackGapSeconds ?? playback.gap.defaultSeconds}
        seconds={progress.settings.playbackGapSeconds ?? playback.gap.defaultSeconds}
        disabled={busy}
        onSave={(playbackGapSeconds) =>
          void act(async () => {
            await api('/household/settings', {
              method: 'PUT',
              body: JSON.stringify({
                soundEnabled: progress.settings.soundEnabled !== false,
                playbackGapSeconds,
              }),
            });
            await refresh();
          })
        }
      />
      <p>减少动态效果</p>
      <ReducedMotionControl
        checked={Boolean(progress.settings.reducedMotion)}
        disabled={busy}
        onChange={(next) =>
          void act(async () => {
            await api('/household/settings', {
              method: 'PUT',
              body: JSON.stringify({
                soundEnabled: progress.settings.soundEnabled !== false,
                reducedMotion: next,
              }),
            });
            await refresh();
          })
        }
      />
    </section>
  );
}
