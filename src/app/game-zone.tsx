import { PinyinShop } from './pinyin-shop';
import { shopRules } from '../domain/pinyin-shop';
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

import { levelCatalog } from '../domain/game-levels';

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
  guidanceEnabled,
  onGuidanceChange,
}: {
  curriculum: Curriculum;
  lessonId: string;
  voice: Voice;
  busy: boolean;
  guidanceEnabled: boolean;
  onGuidanceChange: (enabled: boolean) => void;
  onStart: (id: string, levelId: string) => void;
  onBack: () => void;
}) {
  const [shopOpen, setShopOpen] = useState(false);
  const [selectedLevels, setSelectedLevels] = useState<Record<string, string>>({});
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
  const [settledRevision, setSettledRevision] = useState(-1);
  const [revision, setRevision] = useState(0);
  const loading = settledRevision !== revision;
  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(
      () => controller.abort(),
      gameCatalog.policy.requestTimeoutSeconds * 1000,
    );
    void api('/games', { signal: controller.signal })
      .then((value) => {
        if (alive) {
          setData(value as GameOverview);
          setError('');
        }
      })
      .catch((reason: Error) => {
        if (alive) setError(controller.signal.aborted ? 'MAC_UNREACHABLE' : reason.message);
      })
      .finally(() => {
        window.clearTimeout(timeout);
        if (alive) setSettledRevision(revision);
      });
    return () => {
      alive = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [revision]);
  const order = curriculum.lessons.find((item) => item.id === lessonId)?.order ?? 0;
  const ids = new Set(
    curriculum.lessons.filter((item) => item.order <= order).flatMap((item) => item.exerciseIds),
  );
  if (shopOpen)
    return (
      <PinyinShop
        curriculum={curriculum}
        lessonId={lessonId}
        guidanceEnabled={guidanceEnabled}
        onGuidanceChange={onGuidanceChange}
        onExit={() => {
          setShopOpen(false);
          setRevision((v) => v + 1);
        }}
      />
    );
  return (
    <section className="game-zone" aria-label="拼音游戏乐园">
      <header className="game-zone-heading">
        <div>
          <span className="eyebrow">听一听 · 玩一玩</span>
          <h1>拼音游戏乐园</h1>
          <p>选一款喜欢的游戏，听清拼音就出发。</p>
        </div>
        <nav className="game-zone-nav" aria-label="乐园导航">
          <button className="quiet" onClick={onBack}>
            ← 回到学习
          </button>
          <VoiceButton id="ui-game_welcome" voice={voice} label="听游戏怎么玩" text="听介绍" />
        </nav>
      </header>
      <VoiceFailure voice={voice} />
      <aside className="game-budget" aria-label="游戏时长约定" aria-busy={loading}>
        <div className="game-budget-status">
          {data ? (
            <>
              <strong>今天已玩 {Math.ceil(data.clock.dailySeconds / 60)} 分钟</strong>
              <span>
                每次最多 {data.clock.sessionMinutes} 分钟 · 每天最多 {data.clock.dailyMinutes} 分钟
              </span>
            </>
          ) : (
            <span role="status">{error ? '可玩时间暂未确认' : '正在确认可玩时间…'}</span>
          )}
        </div>
        <button
          className="quiet"
          aria-label="刷新可玩时间"
          disabled={loading}
          onClick={() => setRevision((v) => v + 1)}
        >
          {loading ? '正在刷新…' : '↻ 刷新时间'}
        </button>
        {data?.clock.reason && (
          <p className="game-budget-reason" role="status">
            {errorMessage(data.clock.reason)}
            {data.clock.reason === 'GAME_SESSION_LIMIT'
              ? ` 还需休息约 ${Math.ceil(data.clock.breakRemainingSeconds / 60)} 分钟。`
              : ''}
          </p>
        )}
      </aside>
      <Notice error={error} onReconnect={() => setRevision((v) => v + 1)} />
      <article className="shop-entry">
        <span className="shop-entry-icon" aria-hidden="true">
          🍊
        </span>
        <div>
          <div className="shop-entry-title">
            <h2>拼音小卖部</h2>
            <span className="shop-mode-badge">
              {shopRules.recognitionMode === 'mock' ? '模拟体验 · 非真实识别' : '口头拼读'}
            </span>
          </div>
          <p>
            {shopRules.shelves.length} 个货架 · {shopRules.products.length} 件商品 ·{' '}
            {shopRules.recognitionMode === 'mock' ? '模拟入车，不计学习成绩' : '读拼音，装满购物篮'}
          </p>
        </div>
        <div className="shop-entry-actions">
          <VoiceButton
            id={shopRules.recognitionMode === 'mock' ? 'ui-shop_mock_welcome' : 'ui-shop_welcome'}
            voice={voice}
            label="听小卖部怎么玩"
            text="听玩法"
          />
          <button
            aria-label="进入拼音小卖部"
            disabled={busy || loading || !!error || !data || !!data.clock.reason}
            onClick={() => {
              voice.stop();
              setShopOpen(true);
            }}
          >
            逛小卖部 →
          </button>
        </div>
      </article>
      <div className="game-grid">
        {gameCatalog.games.map((game) => {
          const available = curriculum.exercises.some(
            (q) => ids.has(q.id) && game.modes.includes(q.type) && !!q.audioRef,
          );
          const routes = levelCatalog.levels.filter((l) => l.gameId === game.id);
          const preference = preferences[game.id]!;
          const match =
            preference.difficulty === 'auto'
              ? (data?.recommendation?.level ?? 'gentle')
              : preference.difficulty;
          const speed =
            preference.speed === 'auto'
              ? (data?.recommendation?.speed ?? 'slow')
              : preference.speed;
          const chosen =
            routes.find((l) => l.id === selectedLevels[game.id]) ??
            routes.find((l) => l.recommendedDifficulty === match) ??
            routes[0]!;
          return (
            <article className={`game-card game-${game.id}`} key={game.id}>
              <header className="game-card-heading">
                <span className="game-card-icon" aria-hidden="true">
                  {game.icon}
                </span>
                <div>
                  <h2>{game.title}</h2>
                  <p>{game.description}</p>
                </div>
              </header>
              <div className="game-card-pickers">
                <label>
                  关卡
                  <select
                    aria-label={`${game.title}关卡`}
                    value={chosen.id}
                    onChange={(e) =>
                      setSelectedLevels({ ...selectedLevels, [game.id]: e.target.value })
                    }
                  >
                    {routes.map((route) => (
                      <option value={route.id} key={route.id}>
                        第{route.number}关 · {route.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  每关题量
                  <select
                    aria-label={`${game.title}每关题量`}
                    value={preferences[game.id]?.taskCount ?? gameCatalog.play.defaultTasks}
                    onChange={(e) =>
                      changePreference(game.id, { taskCount: Number(e.target.value) })
                    }
                  >
                    {Array.from(
                      { length: gameCatalog.play.maxTasks - gameCatalog.play.minTasks + 1 },
                      (_, i) => gameCatalog.play.minTasks + i,
                    ).map((n) => (
                      <option key={n} value={n}>
                        {n} 个拼音
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <details className="game-card-settings">
                <summary aria-label={`${game.title}设置`}>
                  <span>
                    难度{' '}
                    {preference.difficulty === 'auto' && !data
                      ? '自动'
                      : gameCatalog.levels[match].label}{' '}
                    · 速度{' '}
                    {preference.speed === 'auto' && !data
                      ? '自动'
                      : gameCatalog.speeds[speed].label}
                  </span>
                  <span className="game-card-adjust">
                    调整 <span aria-hidden="true">⌄</span>
                  </span>
                </summary>
                <div className="game-preferences">
                  <label>
                    难度
                    <select
                      aria-label={`${game.title}难度`}
                      value={preferences[game.id]?.difficulty ?? 'auto'}
                      onChange={(event) => {
                        setSelectedLevels((prior) => ({ ...prior, [game.id]: chosen.id }));
                        changePreference(game.id, {
                          difficulty: event.target.value as ScenePreference['difficulty'],
                        });
                      }}
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
                <div className="game-level-story">
                  <p>{chosen.subtitle}</p>
                  <span>
                    3 个章节 · 第 {chosen.number} 关速度 ×
                    {(1 + (chosen.number - 1) * gameCatalog.play.levelSpeedStep).toFixed(2)}
                  </span>
                  <VoiceButton
                    id={chosen.voiceId}
                    voice={voice}
                    label={`听关卡故事：${chosen.title}`}
                    text="听关卡故事"
                  />
                </div>
              </details>
              <div className="game-card-actions">
                <VoiceButton
                  id={game.voiceId}
                  voice={voice}
                  label={`听玩法：${game.title}`}
                  text="听玩法"
                />
                <button
                  className="game-start"
                  disabled={
                    busy || loading || !!error || !data || !!data.clock.reason || !available
                  }
                  onClick={() => onStart(game.id, chosen.id)}
                >
                  开始{game.title} →
                </button>
              </div>
              {!available && <p className="game-unavailable">学到相关课程后开放</p>}
            </article>
          );
        })}
      </div>
      <div className="game-home-details">
        <details className="game-home-info">
          <summary>时长与难度推荐说明</summary>
          <p>
            连续休息 10 分钟，才算新的一次。每关可选 3～20 个拼音任务，默认 6
            个，游戏内也能调难度和速度。
          </p>
          <p>
            当前推荐：{gameCatalog.levels[data?.recommendation?.level ?? 'gentle'].label} ·{' '}
            {gameCatalog.speeds[data?.recommendation?.speed ?? 'slow'].label}
            。依据已学范围内最近有效作答（{data?.recommendation?.sampleSize ?? 0}{' '}
            个样本），操作快慢不计掌握度。
          </p>
          {isGuest() && (
            <p>访客时长仅暂存在此标签页，清除访客会重置。连接家庭后，使用跨设备共享的时长约定。</p>
          )}
        </details>
        {data && (
          <details className="game-home-evidence">
            <summary>
              查看学习记录 <span>近 7 天 · {data.report.answered} 次作答</span>
            </summary>
            <GameEvidence data={data} curriculum={curriculum} />
          </details>
        )}
      </div>
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
