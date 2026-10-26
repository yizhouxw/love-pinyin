import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Curriculum } from '../domain/learning-api';
import type { PronunciationService } from '../domain/pronunciation';
import {
  addShopProduct,
  shopProducts,
  shopTargets,
  shopRules,
  shopTotalCents,
  shopPrice,
  type ShopProduct,
  type ShopTarget,
} from '../domain/pinyin-shop';
import { BrowserShopRecorder } from '../platform/audio/browser-shop-recorder';
import {
  ShopReadingSession,
  type ShopReadingOutcome,
} from '../platform/audio/shop-reading-session';
import { shopPronunciation } from '../platform/audio/shop-pronunciation';
import { useLearningVoice } from './learning-voice';
import { GuidanceSwitch } from './guidance-switch';
import { ShopProductImage } from './shop-product-image';
import { useGameClock } from './use-game-clock';
import { errorMessage } from './notice';
import './pinyin-shop.css';

type Feedback = 'welcome' | 'ready' | ShopReadingOutcome | 'complete';
const messages: Record<Feedback, string> = {
  welcome: '挑一件喜欢的商品，看看右边的拼音，直接读出来。',
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
    () => recognition ?? shopPronunciation(targets.map((p) => p.target)),
    [recognition, targets],
  );
  const voice = useLearningVoice('pinyin-shop');
  const stopVoice = voice.stop;
  const playVoice = voice.play;
  const [reading] = useState(
    () =>
      new ShopReadingSession(
        new BrowserShopRecorder(shopRules.recognitionTimeoutMs),
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
  const nextTarget = useRef(0);
  const challenge = useRef<HTMLDivElement>(null);
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
      if (guidance.current) playVoice('ui-shop_welcome');
    }
  }, [clock.paused, playVoice]);

  function tell(next: Feedback) {
    setFeedback(next);
    if (guidance.current) voice.play(`ui-shop_${next}`);
  }
  const full = basket.length >= shopRules.basketLimit;
  const shelf = shopRules.shelves[cabinet]!;
  const goods = products.filter((p) => p.shelfId === shelf.id);
  function read(product: ShopProduct, task: ShopTarget) {
    cancel();
    const generation = epoch.current;
    setPhase('starting');
    setFeedback('ready');
    void reading.start(task.target, {
      phase: (value) => {
        if (epoch.current === generation) setPhase(value);
      },
      outcome: (outcome) => {
        if (epoch.current !== generation || document.hidden) return;
        setPhase('ready');
        if (outcome === 'matched') {
          const next = addShopProduct(basketRef.current, product.id);
          basketRef.current = next;
          setBasket(next);
          setSelected(null);
          setTarget(null);
          tell('matched');
        } else tell(outcome);
      },
    });
  }
  function choose(product: ShopProduct) {
    if (finished || full || clock.paused || basketRef.current.includes(product.id)) return;
    const task = targets[nextTarget.current % targets.length];
    nextTarget.current += 1;
    setSelected(product);
    setTarget(task ?? null);
    if (window.matchMedia('(max-width: 800px)').matches)
      challenge.current?.scrollIntoView({ behavior: 'instant', block: 'start' });
    if (task) read(product, task);
    else {
      cancel();
      setPhase('ready');
      tell('unavailable');
    }
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
  const feedbackText =
    phase === 'starting'
      ? '正在打开麦克风，首次使用请允许权限。'
      : phase === 'listening'
        ? '我在听，直接读出右边的拼音…'
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
          <strong>开发模拟演示</strong> · 不判断声音，匹配固定成功，不记录学习成绩。
        </aside>
      )}
      {!adapter.mock && adapter.configured === false && (
        <aside className="shop-mode">
          真实识别尚未配置，录音后会提示不可用；可听示范跟读，不作发音判断。
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
                      <span>{product.name}</span>
                      <strong>{shopPrice(product.priceCents)}</strong>
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
                <span className="eyebrow">
                  {finished
                    ? '本次购物结束'
                    : selected
                      ? '读这个拼音，商品就来啦'
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
                <h2 className="shop-target">
                  {target?.target.pinyin ?? (finished ? '购物清单' : '等你来挑')}
                </h2>
                <div className="shop-listening-indicator" aria-hidden="true">
                  {phase === 'listening' ? (
                    <>
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                    </>
                  ) : (
                    <span>
                      {phase === 'starting' ? '🎙' : full ? '✓ 购物车装好啦' : '选商品后自动开始听'}
                    </span>
                  )}
                </div>
                <p className="shop-feedback" role="status">
                  {feedbackText}
                </p>
                {target && selected && phase === 'ready' && !finished && (
                  <div className="shop-record-controls">
                    <button className="shop-primary" onClick={() => read(selected, target)}>
                      🎙 再读一次
                    </button>
                    <button
                      className="quiet"
                      onClick={() => {
                        cancel();
                        setPhase('ready');
                        voice.playSequence([{ id: target.audioRef, kind: target.audioKind }]);
                      }}
                    >
                      🔊 听示范
                    </button>
                  </div>
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
                {feedback === 'matched' && !full && (
                  <button
                    className="quiet shop-return-shelf"
                    onClick={() =>
                      display.current?.scrollIntoView({ behavior: 'instant', block: 'start' })
                    }
                  >
                    继续挑商品 ↑
                  </button>
                )}
                {voice.failureId && (
                  <p role="alert" className="shop-audio-error">
                    提示声音暂时没有响起，可以继续练习。请家长检查本机声音。
                  </p>
                )}
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
                {adapter.mock && <p className="shop-simulation">模拟购物清单</p>}
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
                  <p className="shop-empty">读音匹配后，喜欢的商品会自动来到这里。</p>
                )}
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
            每次最多六件，选好就结算。录音仅在内存处理，退出清除；口头练习不计客观题掌握度。
            {adapter.mock ? '当前为固定成功模拟，不判断发音。' : '真实识别能力以接入的服务为准。'}
          </footer>
        </>
      )}
    </section>
  );
}
