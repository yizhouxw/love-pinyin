import { useEffect, useState } from 'react';
import { gameCatalog, type GameOverview } from '../domain/games';
import type { Curriculum } from '../domain/learning-api';
import { api } from '../platform/api-client';
import { isGuest } from '../platform/guest';
import {
  readScenePreference,
  saveScenePreference,
  type ScenePreference,
} from '../platform/game-preferences';
import { VoiceButton, VoiceFailure, type useLearningVoice } from './learning-voice';
import { Notice, errorMessage } from './notice';

type Voice = ReturnType<typeof useLearningVoice>;
export function GameEvidence({ data, curriculum }: { data: GameOverview; curriculum: Curriculum }) {
  const report = data.report;
  return (
    <section className="game-evidence" aria-label="游戏学习效果">
      <h2>这 7 天的游戏收获</h2>
      <div className="game-stats">
        <span>
          <strong>{report.answered}</strong> 次作答
        </span>
        <span>
          <strong>{report.independentCorrect}</strong> 次首次独立答对
        </span>
        <span>
          <strong>{report.hints}</strong> 次使用提示
        </span>
        <span>
          <strong>{report.skipped}</strong> 次跳过
        </span>
      </div>
      {report.answered === 0 ? (
        <p>完成一关后，这里就会留下真实的学习记录。</p>
      ) : (
        <>
          <p>
            需要再练：
            {report.practiceKnowledgeIds.length
              ? report.practiceKnowledgeIds
                  .map(
                    (id) => curriculum.knowledgeItems.find((item) => item.id === id)?.symbol ?? id,
                  )
                  .join('、')
              : '暂未发现新的待巩固点，继续按课程慢慢学。'}
          </p>
          <p>
            每次作答只记录首次结果，修正不会覆盖；同题多次练习会重复计入次数。样本较少时先观察，详细掌握度可在家长学习记录中查看，不是考试或发音评分。
            {report.pendingClock > 0 ? `其中 ${report.pendingClock} 次待校时，不计独立答对。` : ''}
          </p>
        </>
      )}
    </section>
  );
}

export function GameZone({
  curriculum,
  lessonId,
  voice,
  busy,
  onStart,
  onBack,
}: {
  curriculum: Curriculum;
  lessonId: string;
  voice: Voice;
  busy: boolean;
  onStart: (id: string) => void;
  onBack: () => void;
}) {
  const [preferences, setPreferences] = useState(() =>
    Object.fromEntries(gameCatalog.games.map((g) => [g.id, readScenePreference(g.id)])),
  );
  function changePreference(id: string, value: Partial<ScenePreference>) {
    const next = { ...preferences[id]!, ...value };
    saveScenePreference(id, next);
    setPreferences({ ...preferences, [id]: next });
  }
  const [data, setData] = useState<GameOverview | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let alive = true;
    void api('/games')
      .then((value) => {
        if (alive) {
          setData(value as GameOverview);
          setError('');
        }
      })
      .catch((reason: Error) => {
        if (alive) setError(reason.message);
      });
    return () => {
      alive = false;
    };
  }, [revision]);
  const order = curriculum.lessons.find((item) => item.id === lessonId)?.order ?? 0;
  const ids = new Set(
    curriculum.lessons.filter((item) => item.order <= order).flatMap((item) => item.exerciseIds),
  );
  return (
    <section className="game-zone" aria-label="拼音游戏乐园">
      <button className="quiet" onClick={onBack}>
        ← 回到学习
      </button>
      <header className="game-zone-heading">
        <span className="eyebrow">听一听 · 玩一玩 · 学一点</span>
        <h1>拼音游戏乐园</h1>
        <p>跑一跑、划一划、敲一敲、送一送。每次 6 个目的地，听学过的拼音，玩自己的节奏。</p>
        <VoiceButton id="ui-game_welcome" voice={voice} label="听游戏怎么玩" />
        <VoiceFailure voice={voice} />
      </header>
      {data && (
        <aside className="game-budget" aria-label="游戏时长约定">
          <strong>
            每次最多 {data.clock.sessionMinutes} 分钟 · 每天最多 {data.clock.dailyMinutes} 分钟
          </strong>
          <span>
            今天已玩 {Math.ceil(data.clock.dailySeconds / 60)} 分钟。连续休息 10
            分钟，才算新的一次。
          </span>
          {data.clock.reason && (
            <p role="status">
              {errorMessage(data.clock.reason)}
              {data.clock.reason === 'GAME_SESSION_LIMIT'
                ? ` 还需休息约 ${Math.ceil(data.clock.breakRemainingSeconds / 60)} 分钟。`
                : ''}
            </p>
          )}
          <button className="quiet" onClick={() => setRevision((value) => value + 1)}>
            刷新可玩时间
          </button>
        </aside>
      )}
      {isGuest() && (
        <p className="adult-hint">
          访客时长仅暂存在此标签页；清除访客会重置。请连接家庭，使用跨设备共享的时长约定。
        </p>
      )}
      <Notice error={error} onReconnect={() => setRevision((value) => value + 1)} />
      <div className="game-grid">
        {gameCatalog.games.map((game) => {
          const available = curriculum.exercises.some(
            (q) => ids.has(q.id) && game.modes.includes(q.type) && !!q.audioRef,
          );
          return (
            <article className={`game-card game-${game.id}`} key={game.id}>
              <div className="game-card-icon" aria-hidden="true">
                {game.icon}
              </div>
              <h2>{game.title}</h2>
              <p>{game.description}</p>
              <div className="game-preferences">
                <label>
                  难度
                  <select
                    aria-label={`${game.title}难度`}
                    value={preferences[game.id]?.difficulty ?? 'auto'}
                    onChange={(event) =>
                      changePreference(game.id, {
                        difficulty: event.target.value as ScenePreference['difficulty'],
                      })
                    }
                  >
                    <option value="auto">按进度匹配</option>
                    {Object.entries(gameCatalog.levels).map(([key, value]) => (
                      <option key={key} value={key}>
                        {value.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  速度
                  <select
                    aria-label={`${game.title}速度`}
                    value={preferences[game.id]?.speed ?? 'auto'}
                    onChange={(event) =>
                      changePreference(game.id, {
                        speed: event.target.value as ScenePreference['speed'],
                      })
                    }
                  >
                    <option value="auto">自动</option>
                    {Object.entries(gameCatalog.speeds).map(([key, value]) => (
                      <option key={key} value={key}>
                        {value.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <p className="game-recommendation">
                当前推荐：{gameCatalog.levels[data?.recommendation?.level ?? 'gentle'].label} ·{' '}
                {gameCatalog.speeds[data?.recommendation?.speed ?? 'slow'].label}
                。依据已学范围内最近有效作答（{data?.recommendation?.sampleSize ?? 0}{' '}
                个样本）；操作快慢不计掌握度。
              </p>
              <VoiceButton id={game.voiceId} voice={voice} label={`听玩法：${game.title}`} />
              <button
                className="game-start"
                disabled={busy || !data || !!data.clock.reason || !available}
                onClick={() => onStart(game.id)}
              >
                开始{game.title} →
              </button>
              {!available && <p>学到相关课程后开放</p>}
            </article>
          );
        })}
      </div>
      {data && <GameEvidence data={data} curriculum={curriculum} />}
    </section>
  );
}

export function GamePause({
  reason,
  voice,
  onResume,
  onExit,
  busy,
}: {
  reason: string;
  voice: Voice;
  onResume: () => void;
  onExit: () => void;
  busy: boolean;
}) {
  const limit = reason === 'GAME_SESSION_LIMIT' || reason === 'GAME_DAILY_LIMIT';
  return (
    <main className="play-page">
      <section className="question-card game-pause" aria-label="游戏已暂停">
        <span className="mascot" aria-hidden="true">
          🌿
        </span>
        <h1>{limit ? '该休息一下啦' : '游戏先暂停一下'}</h1>
        <p>{reason ? errorMessage(reason) : '正在确认游戏时间，请稍等。'}</p>
        <p>已答的题目会保留，这次暂停不会算答错。</p>
        <VoiceButton
          id={limit ? 'ui-game_rest' : 'ui-game_paused'}
          voice={voice}
          label="听暂停提醒"
        />
        <VoiceFailure voice={voice} />
        <button className="next-button" disabled={busy} onClick={onExit}>
          保存并回游戏乐园
        </button>
        <button className="quiet" disabled={busy} onClick={onResume}>
          {limit ? '休息后检查时间' : '继续游戏'}
        </button>
      </section>
    </main>
  );
}
