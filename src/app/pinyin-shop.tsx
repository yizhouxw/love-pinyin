import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Curriculum } from '../domain/learning-api';
import type { PronunciationService } from '../domain/pronunciation';
import {
  addShopProduct,
  shopOutcome,
  shopProducts,
  shopRules,
  type ShopProduct,
} from '../domain/pinyin-shop';
import { BrowserReadingRecorder } from '../platform/audio/browser-reading-recorder';
import { recordingWav } from '../platform/audio/recording-wav';
import { shopPronunciation } from '../platform/audio/shop-pronunciation';
import { useLearningVoice, VoiceButton, VoiceFailure } from './learning-voice';
import { useGameClock } from './use-game-clock';
import { GamePause } from './game-zone';
import './pinyin-shop.css';

type Phase = 'ready' | 'starting' | 'recording' | 'matching';
type Feedback =
  | 'welcome'
  | 'ready'
  | 'matched'
  | 'retry'
  | 'uncertain'
  | 'unavailable'
  | 'microphone'
  | 'complete';
const messages: Record<Feedback, string> = {
  welcome: '选一件喜欢的商品，读包装上的拼音。',
  ready: '听一听，再点麦克风。读完点「完成录音」。',
  matched: '读音匹配，商品自动放进购物篮啦！',
  retry: '这次读音还没有匹配。听示范，慢慢读，再试一次。',
  uncertain: '刚才没有听清楚，不算读错。靠近麦克风再试试。',
  unavailable: '自动识别暂不可用，不算读错。可以先听示范、跟着读。',
  microphone: '没有录到声音。请家长检查麦克风权限，再试一次。',
  complete: '购物篮装好啦！看看你的收获，休息一下吧。',
};

export function PinyinShop({
  curriculum,
  lessonId,
  onExit,
  recognition,
}: {
  curriculum: Curriculum;
  lessonId: string;
  onExit: () => void;
  /** Composition seam for a verified MATCH-10 acoustic service. Never supplied by children. */
  recognition?: { service: PronunciationService; mock: boolean; configured?: boolean };
}) {
  const products = useMemo(() => shopProducts(curriculum, lessonId), [curriculum, lessonId]);
  const adapter = useMemo(
    () => recognition ?? shopPronunciation(products.map((p) => p.target)),
    [recognition, products],
  );
  const configured = adapter.mock || adapter.configured !== false;
  const voice = useLearningVoice('pinyin-shop');
  const stopVoice = voice.stop;
  const [recorder] = useState(() => new BrowserReadingRecorder(30_000));
  const [selected, setSelected] = useState<ShopProduct | null>(null);
  const [basket, setBasket] = useState<string[]>([]);
  const [phase, setPhase] = useState<Phase>('ready');
  const [feedback, setFeedback] = useState<Feedback>('welcome');
  const [finished, setFinished] = useState(false);
  const [cabinet, setCabinet] = useState(0);
  const epoch = useRef(0);
  const locked = useRef(false);
  const active = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancel = useCallback(() => {
    epoch.current += 1;
    active.current?.abort();
    active.current = null;
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    recorder.discard();
    locked.current = false;
    stopVoice();
  }, [recorder, stopVoice]);
  const controlsVoice = {
    ...voice,
    play: (id: string) => {
      cancel();
      setPhase('ready');
      voice.play(id);
    },
    stop: () => {
      cancel();
      setPhase('ready');
    },
    retry: () => {
      cancel();
      setPhase('ready');
      voice.retry();
    },
  };
  const clock = useGameClock(!finished, cancel);
  useEffect(() => {
    if (clock.paused) cancel();
  }, [clock.paused, cancel]);
  useEffect(() => cancel, [cancel]);
  const full = basket.length >= Math.min(shopRules.basketLimit, products.length);
  const unavailable = !configured;
  const shelf = products.slice(cabinet * 6, cabinet * 6 + 6);
  const pages = Math.ceil(products.length / 6);
  function tell(next: Feedback) {
    setFeedback(next);
    voice.play(`ui-shop_${next}`);
  }
  function choose(product: ShopProduct) {
    cancel();
    setPhase('ready');
    setSelected(product);
    setFeedback('ready');
    voice.playSequence([
      { id: 'ui-shop_ready', kind: 'private' },
      { id: product.audioRef, kind: product.audioKind },
    ]);
  }
  async function matchRecording(url: string, product: ShopProduct, generation: number) {
    if (epoch.current !== generation) return;
    setPhase('matching');
    const controller = new AbortController();
    active.current = controller;
    const requestId = crypto.randomUUID();
    timer.current = setTimeout(() => {
      if (epoch.current !== generation) return;
      cancel();
      setPhase('ready');
      tell('unavailable');
    }, shopRules.recognitionTimeoutMs);
    try {
      const audio = await recordingWav(url, controller.signal);
      if (epoch.current !== generation || controller.signal.aborted) return;
      const result = await adapter.service.match({
        requestId,
        targetId: product.target.id,
        audio,
        signal: controller.signal,
      });
      if (epoch.current !== generation || controller.signal.aborted || document.hidden) return;
      const outcome = shopOutcome(result, requestId, product.target.id, adapter.mock);
      cancel();
      setPhase('ready');
      if (outcome === 'matched') {
        const next = addShopProduct(basket, product.id);
        setBasket(next);
        setSelected(null);
        if (next.length >= Math.min(shopRules.basketLimit, products.length)) {
          setFinished(true);
          tell('complete');
        } else tell('matched');
      } else tell(outcome === 'stale' ? 'unavailable' : outcome);
    } catch (error) {
      if (epoch.current !== generation || controller.signal.aborted) return;
      cancel();
      setPhase('ready');
      tell(
        error instanceof Error && error.message === 'READING_TOO_LONG'
          ? 'uncertain'
          : 'unavailable',
      );
    }
  }
  async function startRecording() {
    if (!selected || locked.current || clock.paused || !configured || full || finished) return;
    cancel();
    locked.current = true;
    const generation = epoch.current;
    const product = selected;
    setPhase('starting');
    try {
      await recorder.start(
        (url) => {
          void matchRecording(url, product, generation);
        },
        () => {
          if (epoch.current !== generation) return;
          cancel();
          setPhase('ready');
          tell('microphone');
        },
      );
      if (epoch.current === generation) setPhase('recording');
    } catch {
      if (epoch.current !== generation) return;
      cancel();
      setPhase('ready');
      tell('microphone');
    }
  }
  const exit = () => {
    cancel();
    onExit();
  };
  if (clock.paused && !finished)
    return (
      <GamePause
        reason={clock.reason}
        voice={controlsVoice}
        busy={false}
        onExit={exit}
        onResume={() => {
          cancel();
          setPhase('ready');
          void clock.resume();
        }}
      />
    );
  return (
    <section className="pinyin-shop" aria-label="拼音小卖部">
      <header className="shop-topbar">
        <button className="quiet" onClick={exit}>
          ← 回游戏乐园
        </button>
        <span>选一选 · 读一读 · 装一篮</span>
        {!finished && (
          <button
            className="quiet"
            onClick={() => {
              cancel();
              setPhase('ready');
              clock.pause('GAME_PAUSED');
            }}
          >
            ⏸ 暂停
          </button>
        )}
      </header>
      <div className="shop-sign">
        <span aria-hidden="true">🍊</span>
        <div>
          <small>今天也来读一点</small>
          <h1>拼音小卖部</h1>
        </div>
        <span className="shop-stamp">一篮小收获</span>
      </div>
      {adapter.mock && (
        <aside className="shop-mode" role="status">
          <strong>开发模拟演示</strong> · 不判断声音，匹配固定成功，不记录学习成绩。
          <VoiceButton id="ui-shop_mock" voice={controlsVoice} label="听模拟说明" />
        </aside>
      )}
      {unavailable && (
        <aside className="shop-mode">
          真实识别尚未配置。现在可以听示范、跟读；接入真实识别后，匹配的商品会自动入篮。
          <VoiceButton id="ui-shop_unavailable" voice={controlsVoice} label="听识别说明" />
        </aside>
      )}
      <div className="shop-layout">
        <div className="shop-display">
          <div className="shop-shelf-heading">
            <h2>挑一件喜欢的</h2>
            <span>包装拼音只取已学内容</span>
          </div>
          <div className="shop-shelves" role="group" aria-label="商品货架">
            {shelf.map((product) => (
              <button
                key={product.id}
                className={`shop-product shop-${product.color}`}
                aria-label={`选择${product.name}`}
                aria-pressed={selected?.id === product.id}
                disabled={finished || full || basket.includes(product.id)}
                onClick={() => choose(product)}
              >
                <span className="shop-package">
                  <span className="shop-package-stripe" />
                  <span className="shop-product-icon" aria-hidden="true">
                    {product.icon}
                  </span>
                  <span className="shop-package-pinyin">{product.target.pinyin}</span>
                </span>
                <span className="shop-price-tag">
                  {product.name}
                  <small>{basket.includes(product.id) ? '✓ 已入篮' : '点我选购'}</small>
                </span>
              </button>
            ))}
          </div>
          {pages > 1 && (
            <nav className="shop-cabinets" aria-label="切换货架">
              <button
                disabled={cabinet === 0 || finished}
                onClick={() => {
                  cancel();
                  setPhase('ready');
                  setCabinet(cabinet - 1);
                }}
              >
                ← 上一柜
              </button>
              <span>
                {cabinet + 1} / {pages}
              </span>
              <button
                disabled={cabinet === pages - 1 || finished}
                onClick={() => {
                  cancel();
                  setPhase('ready');
                  setCabinet(cabinet + 1);
                }}
              >
                下一柜 →
              </button>
            </nav>
          )}
          {!products.length && <p>当前课程没有可用商品，请返回后选择课程。</p>}
        </div>
        <div className="shop-counter">
          <div className="shop-challenge">
            <span className="eyebrow">{finished ? '本次购物完成' : '读包装上的拼音'}</span>
            <div className="shop-selected-icon" aria-hidden="true">
              {finished ? '🧺' : (selected?.icon ?? '🎁')}
            </div>
            <h2 className="shop-target">
              {selected?.target.pinyin ?? (finished ? '收获满满' : '选一件吧')}
            </h2>
            <p>{selected?.name ?? `每次最多 ${shopRules.basketLimit} 件，慢慢选，慢慢读。`}</p>
            {selected && (
              <button
                className="voice-button"
                disabled={finished}
                onClick={() => {
                  cancel();
                  setPhase('ready');
                  voice.playSequence([{ id: selected.audioRef, kind: selected.audioKind }]);
                }}
              >
                🔊 听拼音示范
              </button>
            )}
            <div className="shop-record-controls">
              {phase === 'recording' ? (
                <button
                  className="shop-primary"
                  onClick={() => {
                    setPhase('matching');
                    recorder.stop();
                  }}
                >
                  ✓ 完成录音
                </button>
              ) : (
                <button
                  className="shop-primary"
                  disabled={
                    !selected ||
                    finished ||
                    full ||
                    unavailable ||
                    phase !== 'ready' ||
                    !!voice.playingId
                  }
                  onClick={() => void startRecording()}
                >
                  {phase === 'starting'
                    ? '正在打开麦克风…'
                    : phase === 'matching'
                      ? '正在听你读…'
                      : '🎙 开始录音'}
                </button>
              )}
              {phase !== 'ready' && (
                <button
                  className="quiet"
                  onClick={() => {
                    cancel();
                    setPhase('ready');
                    setFeedback('ready');
                  }}
                >
                  取消本次录音
                </button>
              )}
            </div>
            <p className="shop-feedback" role="status">
              {phase === 'recording'
                ? '正在录音，读完点「完成录音」。'
                : phase === 'matching'
                  ? '正在核对读音，请稍等。'
                  : messages[feedback]}
            </p>
            <VoiceButton id={`ui-shop_${feedback}`} voice={controlsVoice} label="听操作提示" />
            <VoiceFailure voice={controlsVoice} />
          </div>
          <aside
            className={`shop-basket ${finished ? 'shop-basket-complete' : ''}`}
            aria-label="我的购物篮"
          >
            <h2>
              🧺 我的购物篮{' '}
              <span>
                {basket.length} / {Math.min(shopRules.basketLimit, products.length)}
              </span>
            </h2>
            {adapter.mock && <p>模拟购物清单</p>}
            {basket.length ? (
              <ul>
                {basket.map((id) => {
                  const product = products.find((p) => p.id === id)!;
                  return (
                    <li key={id}>
                      <span aria-hidden="true">{product.icon}</span>
                      <span>
                        {product.name}
                        <small>{product.target.pinyin}</small>
                      </span>
                      <span aria-label="已加入">✓</span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="shop-empty">匹配的商品会自动来到这里</p>
            )}
            <button
              className="shop-checkout"
              onClick={() => {
                if (finished) exit();
                else {
                  cancel();
                  setPhase('ready');
                  setSelected(null);
                  setFinished(true);
                  tell('complete');
                }
              }}
            >
              {finished ? '休息，回游戏乐园 →' : '结束本次购物'}
            </button>
          </aside>
        </div>
      </div>
      <footer className="shop-footnote">
        本轮购物篮仅在当前页面保留。录音只在内存处理，退出清除；口头练习不计入客观题掌握度。
        {configured && !adapter.mock
          ? '声调判断以实际服务能力为准。'
          : '当前不判断发音或声调准确度。'}
      </footer>
    </section>
  );
}
