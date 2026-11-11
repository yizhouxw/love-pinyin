import { useState, type ReactNode } from 'react';
import { iosOperation } from '../platform/ios-app';
import { clearPendingLearningAnswers } from '../platform/pending-answer';
import { errorMessage } from './notice';
import type { Lesson, Progress } from '../domain/learning-api';
import { gameCatalog } from '../domain/games';
import { api } from '../platform/api-client';
import { ModelSettings } from './model-settings';
import { ReleaseHistory } from './release-history';

const backupDateKey = 'love-pinyin.ios.last-backup';
function readBackupDate() {
  try {
    const date = Date.parse(localStorage.getItem(backupDateKey) ?? '');
    return Number.isFinite(date) ? date : null;
  } catch {
    return null;
  }
}

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
  const [backupBusy, setBackupBusy] = useState(false);
  const [backupStatus, setBackupStatus] = useState('');
  const [lastBackup, setLastBackup] = useState(readBackupDate);
  async function backup(operation: 'backupExport' | 'backupImport') {
    setBackupBusy(true);
    setBackupStatus('');
    try {
      const { state } = await iosOperation<{ state: string }>(operation);
      if (state === 'restored') {
        clearPendingLearningAnswers();
        setBackupStatus('已恢复学习档案。');
        await refresh();
      } else if (state === 'exported') {
        const date = new Date();
        setLastBackup(date.valueOf());
        try {
          localStorage.setItem(backupDateKey, date.toISOString());
        } catch {
          // The file has already been saved even if preferences are unavailable.
        }
        setBackupStatus('已保存备份。');
      }
    } catch (error) {
      setBackupStatus(
        errorMessage(error instanceof Error ? error.message : 'IOS_BACKUP_UNAVAILABLE'),
      );
    } finally {
      setBackupBusy(false);
    }
  }
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
      <p>记录仅保存在此设备。换设备或删除 App 前，请先把学习备份保存到「文件」。</p>
      <button
        type="button"
        disabled={busy || backupBusy}
        onClick={() => void backup('backupExport')}
      >
        导出学习备份
      </button>
      <button
        type="button"
        className="quiet"
        disabled={busy || backupBusy}
        onClick={() => void backup('backupImport')}
      >
        从 iOS 备份恢复
      </button>
      {lastBackup !== null && (
        <p>
          上次导出：
          {new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(
            lastBackup,
          )}
        </p>
      )}
      <p role="status">{backupStatus}</p>
      {materialInfo}
      <ReleaseHistory contentVersion={contentVersion} />
    </section>
  );
}
