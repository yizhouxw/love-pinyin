import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Curriculum } from '../domain/learning-api';
import type { PronunciationService } from '../domain/pronunciation';
import {
  addShopProduct,
  shopProducts,
  shopSentences,
  shopTargets,
  shopRules,
  shopTotalCents,
  shopPrice,
  type ShopProduct,
  type ShopTarget,
} from '../domain/pinyin-shop';
import { BrowserShopRecorder } from '../platform/audio/browser-shop-recorder';
import { isIOSApp } from '../platform/ios-app';
import { IOSShopRecorder } from '../platform/audio/ios-recorder';
import { MockShopCapture } from '../platform/audio/mock-shop-capture';
import {
  ShopReadingSession,
  type ShopReadingOutcome,
} from '../platform/audio/shop-reading-session';
import { shopPronunciation, shopRecognitionAvailable } from '../platform/audio/shop-pronunciation';
import { useLearningVoice } from './learning-voice';
import { GuidanceSwitch } from './guidance-switch';
import { ShopProductImage } from './shop-product-image';
import { useGameClock } from './use-game-clock';
import { errorMessage } from './notice';
import './pinyin-shop.css';

type Feedback = 'welcome' | 'ready' | 'manual_added' | ShopReadingOutcome | 'complete';
type ReadingMode = 'syllable' | 'sentence';
const quietWaveform = Array<number>(23).fill(0);
const widestSentence = shopSentences.reduce((longest, item) =>
  item.target.pinyin.length > longest.target.pinyin.length ? item : longest,
);

function waveformPath(levels: number[]) {
  return levels
    .map((level, index) => {
      const x = 6 + index * 6;
      const half = Math.round(1 + level * 14);
      return `M${x} ${18 - half}v${half * 2}`;
    })
    .join('');
}

const messages: Record<Feedback, string> = {
  welcome: '挑一件喜欢的商品，看看右边的拼音，直接读出来。',
  manual_added: '已确认读完，商品放进购物车啦！',
  ready: '准备好了可以再读一次，也可以先听示范。',
  matched: '读音匹配，商品已自动加入购物车！',
  retry: '这次读音没有匹配。可以听示范，再读一次。',
  uncertain: '这次没有听清，不算读错。可以再试一次。',
  unavailable: '自动识别暂不可用，不算读错。可以听示范，跟着读。',
  timeout: '这次等待结束了，没有匹配。不算读错，准备好再读一次。',
  microphone: '麦克风没有准备好，请家长检查权限后再试一次。',
  complete: '本次购物结束啦！看看清单和总金额，休息一下吧。',
};

export function PinyinShop({
  curriculum,
  lessonId,
  onExit,
  recognition,
  guidanceEnabled,
  onGuidanceChange,
}: {
  curriculum: Curriculum;
  lessonId: string;
  onExit: () => void;
  recognition?: { service: PronunciationService; mock: boolean; configured?: boolean };
  guidanceEnabled: boolean;
  onGuidanceChange: (enabled: boolean) => void;
}) {
  const products = shopProducts();
  const targets = useMemo(() => shopTargets(curriculum, lessonId), [curriculum, lessonId]);
  const adapter = useMemo(
    () =>
      recognition ?? {
        service: shopPronunciation([...targets, ...shopSentences].map(({ target }) => target)),
        mock: false,
      },
    [recognition, targets],
  );
  const [automatic, setAutomatic] = useState(recognition?.configured ?? !!recognition);
  const [manualOverride, setManualOverride] = useState(false);
  useEffect(() => {
    if (recognition) return;
    const controller = new AbortController();
    void shopRecognitionAvailable(controller.signal).then((available) => {
      if (!controller.signal.aborted) setAutomatic(available);
    });
    return () => controller.abort();
  }, [recognition]);
  const [mode, setMode] = useState<ReadingMode>('syllable');
  const [showHanzi, setShowHanzi] = useState(true);
  const manual = !automatic || manualOverride;
  const voice = useLearningVoice('pinyin-shop');
  const stopVoice = voice.stop;
  const playVoice = voice.play;
  const [reading] = useState(
    () =>
      new ShopReadingSession(
        adapter.mock
          ? new MockShopCapture()
          : isIOSApp()
            ? new IOSShopRecorder(shopRules.recognitionTimeoutMs)
            : new BrowserShopRecorder(shopRules.recognitionTimeoutMs),
        adapter.service,
        adapter.mock,
        shopRules,
      ),
  );
  const [selected, setSelected] = useState<ShopProduct | null>(null);
  const [target, setTarget] = useState<ShopTarget | null>(null);
  const [basket, setBasket] = useState<string[]>([]);
  const basketRef = useRef<string[]>([]);
  const [phase, setPhase] = useState<'ready' | 'starting' | 'listening'>('ready');
  const [feedback, setFeedback] = useState<Feedback>('welcome');
  const [finished, setFinished] = useState(false);
  const [cabinet, setCabinet] = useState(0);
  const nextTarget = useRef({ syllable: 0, sentence: 0 });
  const challenge = useRef<HTMLDivElement>(null);
  const waveform = useRef<SVGPathElement>(null);
  const levels = useRef([...quietWaveform]);
  const display = useRef<HTMLDivElement>(null);
  const epoch = useRef(0);
  const guidance = useRef(guidanceEnabled);
  const cancel = useCallback(() => {
    epoch.current += 1;
    reading.cancel();
    stopVoice();
  }, [reading, stopVoice]);
  const clock = useGameClock(!finished, cancel);
  useEffect(() => {
    if (clock.paused) cancel();
  }, [clock.paused, cancel]);
  useEffect(() => cancel, [cancel]);
  useEffect(() => {
    guidance.current = guidanceEnabled;
    if (!guidanceEnabled) stopVoice();
  }, [guidanceEnabled, stopVoice]);
  const welcomed = useRef(false);
  useEffect(() => {
    if (!clock.paused && !welcomed.current) {
      welcomed.current = true;
      if (guidance.current)
        playVoice(adapter.mock ? 'ui-shop_mock_welcome' : 'ui-shop_manual_welcome');
    }
  }, [clock.paused, playVoice, adapter.mock]);

  function tell(next: Feedback) {
    setFeedback(next);
    if (guidance.current)
      voice.play(next === 'matched' && adapter.mock ? 'ui-shop_mock_added' : `ui-shop_${next}`);
  }
  const full = basket.length >= shopRules.basketLimit;
  const shelf = shopRules.shelves[cabinet]!;
  const goods = products.filter((p) => p.shelfId === shelf.id);
  function addProduct(product: ShopProduct, confirmation: 'matched' | 'manual_added') {
    cancel();
    const next = addShopProduct(basketRef.current, product.id);
    basketRef.current = next;
    setBasket(next);
    setSelected(null);
    setPhase('ready');
    tell(confirmation);
  }
  function read(product: ShopProduct, task: ShopTarget) {
    cancel();
    const generation = epoch.current;
    levels.current.fill(0);
    waveform.current?.setAttribute('d', waveformPath(levels.current));
    setPhase('starting');
    setFeedback('ready');
    void reading.start(task.target, {
      phase: (value) => {
        if (epoch.current === generation) setPhase(value);
      },
      level: (rms) => {
        levels.current.shift();
        levels.current.push(Math.min(1, Math.sqrt(Math.max(0, rms) * 5)));
        waveform.current?.setAttribute('d', waveformPath(levels.current));
      },
      outcome: (outcome) => {
        if (epoch.current !== generation || document.hidden) return;
        setPhase('ready');
        if (outcome === 'matched') addProduct(product, 'matched');
        else {
          if (outcome === 'unavailable' || outcome === 'microphone') setManualOverride(true);
          tell(outcome);
        }
      },
    });
  }
  function prepareTask(product: ShopProduct, nextMode: ReadingMode, startRecording: boolean) {
    cancel();
    const deck = nextMode === 'sentence' ? shopSentences : targets;
    const task = deck[nextTarget.current[nextMode] % deck.length];
    nextTarget.current[nextMode] += 1;
    setSelected(product);
    setTarget(task ?? null);
    setPhase('ready');
    if (!task) {
      tell('unavailable');
      return;
    }
    setFeedback('ready');
    if (startRecording) read(product, task);
    else if (guidance.current)
      voice.playSequence([
        { id: 'ui-shop_manual_read', kind: 'private', optional: true },
        { id: task.audioRef, kind: task.audioKind },
      ]);
  }
  function choose(product: ShopProduct) {
    if (finished || full || clock.paused || basketRef.current.includes(product.id)) return;
    prepareTask(product, mode, !manual);
    if (window.matchMedia('(max-width: 800px)').matches)
      challenge.current?.scrollIntoView({ behavior: 'instant', block: 'start' });
  }
  function changeMode(nextMode: ReadingMode) {
    if (nextMode === mode) return;
    setMode(nextMode);
    if (selected) prepareTask(selected, nextMode, false);
    else {
      cancel();
      setTarget(null);
      setFeedback('welcome');
    }
  }
  function toggleConfirmation() {
    cancel();
    setManualOverride(!manual);
    setPhase('ready');
    setFeedback('ready');
  }
  function listen() {
    if (!target) return;
    cancel();
    setPhase('ready');
    if (phase !== 'ready') setFeedback('ready');
    voice.playSequence([{ id: target.audioRef, kind: target.audioKind }]);
  }
  function changeShelf(index: number) {
    cancel();
    setPhase('ready');
    setSelected(null);
    setTarget(null);
    setFeedback('welcome');
    setCabinet(index);
  }
  const exit = () => {
    cancel();
    onExit();
  };
  const checkout = () => {
    cancel();
    setPhase('ready');
    setSelected(null);
    setTarget(null);
    setFinished(true);
    tell('complete');
  };
  const total = shopPrice(shopTotalCents(basket));
  const canAct = phase === 'ready' && Boolean(target && selected && !finished);
  const canReturn = !full && (feedback === 'matched' || feedback === 'manual_added');
  const signal = adapter.mock
    ? undefined
    : phase === 'listening'
      ? 'listening'
      : feedback === 'matched'
        ? 'matched'
        : undefined;
  const feedbackText =
    phase === 'starting'
      ? adapter.mock
        ? '正在准备模拟识别。'
        : '正在打开麦克风，首次使用请允许权限。'
      : phase === 'listening'
        ? adapter.mock
          ? '正在模拟识别，不判断真实读音…'
          : '我在听，直接读出右边的拼音…'
        : manual && selected && (feedback === 'ready' || feedback === 'welcome')
          ? '听示范，读一读。读完后请自己或家长确认。'
          : feedback === 'matched' && adapter.mock
            ? '模拟完成，商品已加入购物车。现在不是真实识别。'
            : feedback === 'welcome' && adapter.mock
              ? '挑一件喜欢的商品，模拟成功后会自动加入购物车。'
              : messages[feedback];
  return (
    <section className="pinyin-shop" aria-label="拼音小卖部">
      <header className="shop-topbar">
        <button className="quiet" onClick={exit}>
          ← 回游戏乐园
        </button>
        <GuidanceSwitch
          enabled={guidanceEnabled}
          onChange={(enabled) => {
            guidance.current = enabled;
            if (!enabled) voice.stop();
            onGuidanceChange(enabled);
          }}
        />
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
        <div>
          <small>喜欢什么，就挑什么</small>
          <h1>
            拼音小卖部<span>橘子量贩店</span>
          </h1>
        </div>
        <span className="shop-stamp">
          8 大货架
          <br />
          96 件好物
        </span>
      </div>
      {adapter.mock && (
        <aside className="shop-mode" role="status">
          <strong>模拟识别</strong> · 当前不是真实识别，商品会自动加入购物车，不记录学习成绩。
        </aside>
      )}
      {clock.paused && !finished ? (
        <div className="shop-pause" aria-label="游戏已暂停">
          <h2>{clock.reason.includes('LIMIT') ? '该休息一下啦' : '游戏先暂停一下'}</h2>
          <p>{clock.reason ? errorMessage(clock.reason) : '正在确认游戏时间…'}</p>
          <button
            onClick={() => {
              cancel();
              setPhase('ready');
              void clock.resume();
            }}
          >
            继续游戏
          </button>
          <button className="quiet" onClick={exit}>
            回游戏乐园
          </button>
        </div>
      ) : (
        <>
          <div className="shop-layout">
            <div className="shop-display" ref={display}>
              <nav className="shop-cabinets" aria-label="切换货架">
                {shopRules.shelves.map((item, index) => (
                  <button
                    key={item.id}
                    aria-pressed={cabinet === index}
                    disabled={finished}
                    onClick={() => changeShelf(index)}
                  >
                    {index + 1} · {item.name.replace('货架', '')}
                  </button>
                ))}
              </nav>
              <div className="shop-shelf-heading">
                <h2>{shelf.name}</h2>
                <span>第 {cabinet + 1} / 8 架 · 12 件商品</span>
              </div>
              <div className="shop-shelves" role="group" aria-label="商品货架">
                {goods.map((product) => (
                  <button
                    key={product.id}
                    className="shop-product"
                    aria-label={`选择${product.name}`}
                    aria-pressed={selected?.id === product.id}
                    disabled={finished || full || basket.includes(product.id)}
                    onClick={() => choose(product)}
                  >
                    <ShopProductImage product={product} />
                    <span className="shop-price-tag">
                      <span className="shop-price-label">
                        <span>{product.name}</span>
                        <strong>{shopPrice(product.priceCents)}</strong>
                      </span>
                    </span>
                    {basket.includes(product.id) && <span className="shop-added">✓ 已入车</span>}
                  </button>
                ))}
              </div>
              <p className="shop-shelf-note">
                商品只为好玩，和要读的拼音没有关系。价格不影响练习。
              </p>
            </div>
            <div className="shop-counter">
              <div
                ref={challenge}
                className={`shop-challenge ${phase === 'listening' ? 'shop-is-listening' : ''}`}
              >
                {!finished && (
                  <div className="shop-reading-modes" role="group" aria-label="拼读模式">
                    <button
                      aria-pressed={mode === 'syllable'}
                      onClick={() => changeMode('syllable')}
                    >
                      音节拼读
                    </button>
                    <button
                      aria-pressed={mode === 'sentence'}
                      onClick={() => changeMode('sentence')}
                    >
                      句子拼读
                    </button>
                  </div>
                )}
                {!finished && (
                  <div className="shop-confirmation">
                    <strong>{manual ? '人工确认' : adapter.mock ? '模拟' : '本地语音识别'}</strong>
                    <button
                      className="quiet"
                      data-empty={!automatic || undefined}
                      disabled={!automatic}
                      onClick={toggleConfirmation}
                    >
                      {manual ? '切换到本地识别' : '改用人工确认'}
                    </button>
                  </div>
                )}
                <span className="eyebrow">
                  {finished
                    ? '本次购物结束'
                    : selected
                      ? adapter.mock && !manual
                        ? '模拟识别，商品自动入车'
                        : manual
                          ? '听一听，读完再确认'
                          : '读这个拼音，商品就来啦'
                      : '挑一件你喜欢的商品'}
                </span>
                <div className="shop-choice">
                  {selected ? (
                    <>
                      <ShopProductImage product={selected} />
                      <span>
                        {selected.name}
                        <strong>{shopPrice(selected.priceCents)}</strong>
                      </span>
                    </>
                  ) : (
                    <span className="shop-choice-empty" aria-hidden="true">
                      {finished ? '🧾' : '🧺'}
                    </span>
                  )}
                </div>
                <div className="shop-demonstration">
                  <button
                    className="quiet"
                    disabled={!target}
                    aria-pressed={Boolean(target && voice.playingId === target.audioRef)}
                    onClick={listen}
                  >
                    <span aria-hidden="true">🔊 </span>听正确读音
                  </button>
                  <button
                    className="quiet"
                    data-empty={!target?.hanzi || undefined}
                    disabled={!target?.hanzi}
                    onClick={() => setShowHanzi(!showHanzi)}
                  >
                    {showHanzi ? '隐藏汉字' : '显示汉字'}
                  </button>
                </div>
                <div className="shop-reading-text" data-sizer={widestSentence.target.pinyin}>
                  <h2
                    className={
                      !target || target.hanzi ? 'shop-target shop-sentence' : 'shop-target'
                    }
                  >
                    {target?.target.pinyin ?? (finished ? '购物清单' : '等你来挑')}
                  </h2>
                </div>
                <div className="shop-hanzi-space" data-sizer={widestSentence.hanzi}>
                  {target?.hanzi && showHanzi && (
                    <p className="shop-sentence-hanzi">{target.hanzi}</p>
                  )}
                </div>
                <div className="shop-listening-indicator" data-signal={signal} aria-hidden="true">
                  <svg className="shop-signal" viewBox="0 0 144 36">
                    <path
                      className="shop-waveform"
                      ref={waveform}
                      d={waveformPath(quietWaveform)}
                    />
                    <path
                      className="shop-waveform-still"
                      d="M6 16v4 M18 14v8 M30 11v14 M42 7v22 M54 4v28 M66 10v16 M78 6v24 M90 12v12 M102 8v20 M114 13v10 M126 15v6 M138 16v4"
                    />
                  </svg>
                  {!signal && (
                    <span>
                      {phase === 'starting'
                        ? adapter.mock
                          ? '模拟'
                          : '🎙'
                        : full
                          ? '✓ 购物车装好啦'
                          : adapter.mock && !manual
                            ? '选商品后模拟入车'
                            : manual
                              ? '选商品后听读并确认'
                              : '选商品后自动开始听'}
                    </span>
                  )}
                </div>
                <div className="shop-feedback">
                  <p role="status" data-empty={Boolean(voice.failureId) || undefined}>
                    {feedbackText}
                  </p>
                  <p
                    className="shop-audio-error"
                    data-empty={!voice.failureId || undefined}
                    role={voice.failureId ? 'alert' : undefined}
                  >
                    声音暂时没有响起，请点「听正确读音」重试。
                  </p>
                </div>
                <div className="shop-record-controls">
                  <button
                    className="quiet"
                    data-empty={phase === 'ready' || undefined}
                    disabled={phase === 'ready'}
                    onClick={() => {
                      cancel();
                      setPhase('ready');
                      setFeedback('ready');
                    }}
                  >
                    取消本次录音
                  </button>
                  <button
                    className="shop-primary"
                    data-empty={!canAct || !manual || undefined}
                    disabled={!canAct || !manual}
                    onClick={() => {
                      if (selected) addProduct(selected, 'manual_added');
                    }}
                  >
                    读完了，加入购物车
                  </button>
                  <button
                    className="shop-primary"
                    data-empty={!canAct || manual || undefined}
                    disabled={!canAct || manual}
                    onClick={() => {
                      if (selected && target) read(selected, target);
                    }}
                  >
                    🎙 再读一次
                  </button>
                  <button
                    className="quiet shop-return-shelf"
                    data-empty={!canReturn || undefined}
                    disabled={!canReturn}
                    onClick={() =>
                      display.current?.scrollIntoView({ behavior: 'instant', block: 'start' })
                    }
                  >
                    继续挑商品 ↑
                  </button>
                </div>
              </div>
              <aside
                className={`shop-basket ${finished ? 'shop-basket-complete' : ''}`}
                aria-label="我的购物车"
              >
                <h2>
                  我的购物车{' '}
                  <span>
                    {basket.length} / {shopRules.basketLimit} 件
                  </span>
                </h2>
                {adapter.mock && <p className="shop-simulation">模拟购物清单 · 不是真实识别</p>}
                <div
                  className="shop-basket-items"
                  tabIndex={basket.length ? 0 : undefined}
                  role="group"
                  aria-label="购物清单"
                >
                  {basket.length ? (
                    <ul>
                      {basket.map((id) => {
                        const product = products.find((p) => p.id === id)!;
                        return (
                          <li key={id}>
                            <ShopProductImage product={product} />
                            <span>{product.name}</span>
                            <strong>{shopPrice(product.priceCents)}</strong>
                          </li>
                        );
                      })}
                    </ul>
                  ) : (
                    <p className="shop-empty">
                      {adapter.mock
                        ? '选好商品后，会模拟成功并自动入车。'
                        : manual
                          ? '读完并确认后，商品会来到这里。'
                          : '读音匹配后，喜欢的商品会自动来到这里。'}
                    </p>
                  )}
                </div>
                <div className="shop-total">
                  <span>{finished ? '结算总金额' : '合计'}</span>
                  <strong>{total}</strong>
                </div>
                <button className="shop-checkout" onClick={finished ? exit : checkout}>
                  {finished ? '休息，回游戏乐园 →' : '结算购物车 →'}
                </button>
                <small>虚拟购物，没有真实购买或支付。</small>
              </aside>
            </div>
          </div>
          <footer className="shop-footnote">
            每次最多六件，选好就结算。口头练习不计客观题掌握度。
            {adapter.mock
              ? ' 当前为模拟识别，不使用麦克风或判断发音。'
              : manual
                ? ' 听读后人工确认。'
                : ' 录音仅在本机内存处理，退出清除。'}
          </footer>
        </>
      )}
    </section>
  );
}
