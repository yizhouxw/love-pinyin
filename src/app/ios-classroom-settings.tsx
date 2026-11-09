import type { ReactNode } from 'react';
import type { Lesson, Progress } from '../domain/learning-api';
import { gameCatalog } from '../domain/games';
import { api } from '../platform/api-client';
import { ModelSettings } from './model-settings';
import { ReleaseHistory } from './release-history';

export function IOSClassroomSettings({
  lessons,
  contentVersion,
  progress,
  lessonChoice,
  setLessonChoice,
  busy,
  act,
  advancedSettings,
  materialInfo,
  refresh,
}: {
  advancedSettings?: ReactNode;
  materialInfo?: ReactNode;
  lessons: Lesson[];
  contentVersion?: string;
  progress: Progress;
  lessonChoice: string;
  setLessonChoice: (value: string) => void;
  busy: boolean;
  act: (work: () => Promise<void>) => Promise<void>;
  refresh: () => Promise<void>;
}) {
  const progressSummary = `已作答 ${progress.attemptCount ?? 0} 题，完成 ${progress.completedSessions} 轮练习。`;
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
      <h2>游戏时长</h2>
      <form
        className="ios-game-limits"
        onSubmit={(event) => {
          event.preventDefault();
          const values = new FormData(event.currentTarget);
          void act(async () => {
            await api('/household/game-limits', {
              method: 'PUT',
              body: JSON.stringify({
                gameSessionMinutes: Number(values.get('session')),
                gameDailyMinutes: Number(values.get('daily')),
              }),
            });
            await refresh();
          });
        }}
      >
        <label>
          每次最多（分钟）
          <input
            type="number"
            name="session"
            min={1}
            max={gameCatalog.policy.sessionMaxMinutes}
            defaultValue={progress.settings.gameSessionMinutes ?? gameCatalog.policy.sessionMinutes}
            required
          />
        </label>
        <label>
          每天最多（分钟）
          <input
            type="number"
            name="daily"
            min={1}
            max={gameCatalog.policy.dailyMaxMinutes}
            defaultValue={progress.settings.gameDailyMinutes ?? gameCatalog.policy.dailyMinutes}
            required
          />
        </label>
        <button className="quiet" disabled={busy}>
          保存游戏时长
        </button>
      </form>
      <ModelSettings />
      {advancedSettings}
      <h2>此设备学习记录</h2>
      <p role="status" aria-label={progressSummary}>
        {progressSummary}
      </p>
      <p>记录保存在此设备。请保留 App，备份入口将在后续版本提供。</p>
      {materialInfo}
      <ReleaseHistory contentVersion={contentVersion} />
    </section>
  );
}
