import { useEffect, useState } from 'react';
import { gameCatalog, type GameOverview } from '../domain/games';
import type { Curriculum, Progress } from '../domain/learning-api';
import { api } from '../platform/api-client';
import { GameEvidence } from './game-zone';
import { Notice } from './notice';

export function GameSettings({
  progress,
  curriculum,
  busy,
  disabled,
  act,
  refresh,
}: {
  progress: Progress;
  curriculum: Curriculum;
  busy: boolean;
  disabled: boolean;
  act: (work: () => Promise<void>) => Promise<void>;
  refresh: () => Promise<void>;
}) {
  const [single, setSingle] = useState(
    String(progress.settings.gameSessionMinutes ?? gameCatalog.policy.sessionMinutes),
  );
  const [daily, setDaily] = useState(
    String(progress.settings.gameDailyMinutes ?? gameCatalog.policy.dailyMinutes),
  );
  const [saved, setSaved] = useState(false);
  const [data, setData] = useState<GameOverview | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    void api('/games')
      .then((result) => {
        if (alive) setData(result as GameOverview);
      })
      .catch((reason: Error) => {
        if (alive) setError(reason.message);
      });
    return () => {
      alive = false;
    };
  }, [progress.revision]);
  const valid =
    Number.isInteger(Number(single)) &&
    Number(single) >= 1 &&
    Number(single) <= gameCatalog.policy.sessionMaxMinutes &&
    Number.isInteger(Number(daily)) &&
    Number(daily) >= 1 &&
    Number(daily) <= gameCatalog.policy.dailyMaxMinutes;
  return (
    <details className="parent-section">
      <summary>游戏时长与学习效果</summary>
      <p>
        仅控制游戏乐园；课程学习和天天练可照常使用。家庭设备共享额度，切玩法或刷新不会重置；连续停止游戏
        10 分钟后才算新的一次。
      </p>
      <form
        className="game-settings"
        onSubmit={(event) => {
          event.preventDefault();
          if (!valid) return;
          void act(async () => {
            await api('/household/settings', {
              method: 'PUT',
              body: JSON.stringify({
                soundEnabled: progress.settings.soundEnabled,
                gameSessionMinutes: Number(single),
                gameDailyMinutes: Number(daily),
              }),
            });
            await refresh();
            setSaved(true);
          });
        }}
      >
        <label>
          每次游戏最多（分钟）
          <input
            aria-label="每次游戏最多分钟"
            type="number"
            min={1}
            max={gameCatalog.policy.sessionMaxMinutes}
            step={1}
            value={single}
            disabled={disabled || busy}
            onChange={(event) => {
              setSingle(event.target.value);
              setSaved(false);
            }}
          />
        </label>
        <label>
          每天游戏最多（分钟）
          <input
            aria-label="每天游戏最多分钟"
            type="number"
            min={1}
            max={gameCatalog.policy.dailyMaxMinutes}
            step={1}
            value={daily}
            disabled={disabled || busy}
            onChange={(event) => {
              setDaily(event.target.value);
              setSaved(false);
            }}
          />
        </label>
        <p>
          默认每次 15 分钟、每天 60 分钟。每次可设 1～60 分钟，每天可设 1～180
          分钟。到时自动暂停，已答题保留；每日按北京时间零点更新。
        </p>
        <button className="game-start" type="submit" disabled={disabled || busy || !valid}>
          保存游戏时长
        </button>
        {saved && <p role="status">游戏时长已保存，下次游戏时间确认时生效。</p>}
      </form>
      <Notice error={error} onReconnect={() => void act(refresh)} />
      {data && (
        <>
          <p>今天已玩 {Math.ceil(data.clock.dailySeconds / 60)} 分钟。</p>
          <GameEvidence data={data} curriculum={curriculum} />
        </>
      )}
    </details>
  );
}
