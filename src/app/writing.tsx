import { useEffect, useId, useRef, useState } from 'react';
import {
  writingSteps,
  type WritingCatalog,
  type WritingOption,
  type WritingTarget,
} from '../domain/writing';
import { audioPlayer } from '../platform/audio/browser-audio-player';
import { waitForPlaybackGap } from '../platform/audio/playback-gap';
import { useLearningVoice, VoiceButton, VoiceFailure } from './learning-voice';

export function WritingDiagram({
  catalog,
  glyphIds,
  tone,
  step = null,
  offsetY = 0,
  option = false,
}: {
  catalog: WritingCatalog;
  glyphIds: string[];
  tone?: WritingTarget['tone'];
  step?: number | null;
  offsetY?: number;
  option?: boolean;
}) {
  const marker = useId();
  const width = glyphIds.length * catalog.grid.letterWidth + 40;
  const steps = writingSteps({ id: 'diagram', label: '', glyphIds, tone }, catalog);
  return (
    <svg
      className={`writing-diagram ${option ? 'writing-option' : ''}`}
      viewBox={`0 ${option ? -60 : 0} ${width} ${option ? 340 : 220}`}
      aria-hidden="true"
    >
      <defs>
        <marker id={marker} markerWidth="6" markerHeight="6" refX="4" refY="3" orient="auto">
          <path
            d="M0 0 L5 3 L0 6"
            fill="none"
            stroke="var(--writing-guide, #13798b)"
            strokeWidth="1.4"
          />
        </marker>
      </defs>
      {catalog.grid.lines.map((y, i) => (
        <line
          key={y}
          x1="10"
          x2={width - 10}
          y1={y}
          y2={y}
          className={i === 1 || i === 2 ? 'writing-grid-middle' : 'writing-grid-outer'}
        />
      ))}
      {steps.map((item, index) => {
        const { stroke, glyphIndex, kind } = item;
        const active = index === step;
        return (
          <g
            key={index}
            data-stroke={index + 1}
            data-kind={kind}
            data-glyph-index={glyphIndex}
            data-source-stroke={item.strokeIndex}
            transform={`translate(${20 + glyphIndex * catalog.grid.letterWidth},${offsetY + item.offsetY})`}
          >
            <path
              d={stroke.d}
              className={`writing-stroke ${active ? 'active' : step !== null && index > step ? 'future' : ''}`}
            />
            {active && (
              <g className="writing-direction">
                <circle cx={stroke.start[0]} cy={stroke.start[1]} r="6" />
                <path d={stroke.guide} markerEnd={`url(#${marker})`} />
                <text x={stroke.start[0]! - 13} y={stroke.start[1]! - 12}>
                  {index + 1}
                </text>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}

export function WritingChoice({
  catalog,
  value,
}: {
  catalog?: WritingCatalog;
  value: WritingOption;
}) {
  if (!catalog?.glyphs[value.glyphId]) return <span>字卡未加载，请重新连接</span>;
  return (
    <>
      <WritingDiagram catalog={catalog} glyphIds={[value.glyphId]} offsetY={value.offsetY} option />
      <span className="screen-reader-only">
        {catalog.glyphs[value.glyphId]!.symbol} 字卡。{value.description}
      </span>
    </>
  );
}

export function WritingWorkshop({
  catalog,
  lessonId,
  soundEnabled,
}: {
  catalog: WritingCatalog;
  lessonId: string;
  soundEnabled: boolean;
}) {
  const [opened, setOpened] = useState(false);
  const [toneGroup, setToneGroup] = useState(false);
  const allTargets = catalog.lessons[lessonId] ?? [];
  const targets = allTargets.filter((t) => Boolean(t.tone) === toneGroup);
  const [selected, setSelected] = useState(targets[0]?.id);
  const target = targets.find((t) => t.id === selected) ?? targets[0];
  const [step, setStep] = useState<number | null>(null);
  const voice = useLearningVoice(`writing-${lessonId}`);
  const queue = useRef<AbortController | null>(null);
  const continuous = useRef(false);
  const [running, setRunning] = useState(false);
  const [autoNext, setAutoNext] = useState(false);
  const [playFailure, setPlayFailure] = useState(false);
  function stopSequence() {
    queue.current?.abort();
    queue.current = null;
    setRunning(false);
  }
  useEffect(() => {
    const stop = () => {
      if (document.hidden) {
        queue.current?.abort();
        setRunning(false);
      }
    };
    document.addEventListener('visibilitychange', stop);
    return () => {
      queue.current?.abort();
      document.removeEventListener('visibilitychange', stop);
    };
  }, [lessonId]);
  async function demonstrate(next: WritingTarget, choices = targets) {
    stopSequence();
    voice.stop();
    const controller = new AbortController();
    queue.current = controller;
    setRunning(true);
    setPlayFailure(false);
    try {
      for (
        let cursor = choices.findIndex((t) => t.id === next.id);
        cursor < choices.length;
        cursor++
      ) {
        const current = choices[cursor]!;
        setSelected(current.id);
        const sequence = writingSteps(current, catalog);
        for (const [position, item] of sequence.entries()) {
          controller.signal.throwIfAborted();
          setStep(position);
          if (soundEnabled) await audioPlayer.playPrivate(item.audioId, controller.signal);
          await waitForPlaybackGap(soundEnabled ? 0.35 : 1.2, controller.signal);
        }
        setStep(null);
        if (!continuous.current || cursor === choices.length - 1) break;
        await waitForPlaybackGap(1, controller.signal);
      }
    } catch (error) {
      if (!controller.signal.aborted && !(error instanceof Error && error.name === 'AbortError'))
        setPlayFailure(true);
    } finally {
      if (queue.current === controller) {
        queue.current = null;
        setRunning(false);
      }
    }
  }
  if (!target) return null;
  const steps = writingSteps(target, catalog);
  const active = step === null ? null : steps[step]!;
  const activeGlyph = active ? catalog.glyphs[active.glyphId]! : null;
  function selectTarget(next: WritingTarget) {
    void demonstrate(next);
  }
  function showStep(next: number | null) {
    stopSequence();
    voice.stop();
    setStep(next);
    if (soundEnabled) voice.play(next === null ? 'writing-ui-full' : steps[next]!.audioId);
  }
  return (
    <section
      className="writing-workshop"
      aria-label="书写小课堂"
      onClickCapture={(event) => {
        if ((event.target as HTMLElement).closest('.voice-button')) stopSequence();
      }}
    >
      <div className="writing-heading">
        <h3>✎ 看一笔，写一笔</h3>
        <button
          className="quiet"
          aria-expanded={opened}
          onClick={() => {
            stopSequence();
            voice.stop();
            setOpened(!opened);
            if (!opened) void demonstrate(target);
          }}
        >
          {opened ? '收起书写' : '打开书写课堂'}
        </button>
        <VoiceButton id="writing-ui-intro" voice={voice} label="听书写玩法" />
      </div>
      {opened && (
        <>
          <div className="writing-targets" role="group" aria-label="选择书写类型">
            {[false, true].map((tones) => (
              <button
                key={String(tones)}
                className="quiet"
                aria-pressed={toneGroup === tones}
                onClick={() => {
                  stopSequence();
                  voice.stop();
                  setToneGroup(tones);
                  setStep(null);
                  setSelected(allTargets.find((t) => Boolean(t.tone) === tones)?.id);
                  const choices = allTargets.filter((t) => Boolean(t.tone) === tones);
                  if (choices[0]) void demonstrate(choices[0], choices);
                }}
              >
                {tones ? '带声调' : '字母和组合'}
              </button>
            ))}
          </div>
          <p>点选后自动演示完整笔顺；打开连读，接着看下一个。</p>
          <div className="writing-targets" role="group" aria-label="选择书写目标">
            {targets.map((t) => (
              <button
                key={t.id}
                className="quiet"
                aria-pressed={target.id === t.id}
                aria-label={`观察 ${t.label} 的书写`}
                onClick={() => selectTarget(t)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="writing-stage" aria-label={`${target.label} 四线三格示范`}>
            <WritingDiagram
              catalog={catalog}
              glyphIds={target.glyphIds}
              tone={target.tone}
              step={step}
            />
          </div>
          <div className="writing-controls" role="group" aria-label="笔顺播放">
            <button
              className="quiet"
              disabled={targets.indexOf(target) === 0}
              onClick={() => selectTarget(targets[targets.indexOf(target) - 1]!)}
            >
              ← 上一个
            </button>
            <button
              className="start-button"
              onClick={() => (running ? stopSequence() : void demonstrate(target))}
            >
              {running ? '■ 停止演示' : '▶ 重播笔顺'}
            </button>
            <button
              className="quiet"
              aria-pressed={autoNext}
              onClick={() => {
                continuous.current = !autoNext;
                setAutoNext(!autoNext);
              }}
            >
              连读{autoNext ? '：开' : '：关'}
            </button>
            <button
              className="quiet"
              disabled={targets.indexOf(target) === targets.length - 1}
              onClick={() => selectTarget(targets[targets.indexOf(target) + 1]!)}
            >
              下一个 →
            </button>
          </div>
          {playFailure && <p role="alert">声音没有播放成功，请点“重播笔顺”重试。</p>}
          <details>
            <summary>逐笔观察</summary>
            <div className="writing-controls" role="group" aria-label="逐笔操作">
              <button className="quiet" onClick={() => showStep(0)} aria-label="看第一笔">
                ↤ 第一笔
              </button>
              <button
                className="quiet"
                disabled={step === null || step === 0}
                onClick={() => showStep(step! - 1)}
                aria-label="看上一笔"
              >
                ← 上一笔
              </button>
              <button
                className="start-button"
                disabled={step === steps.length - 1}
                onClick={() => showStep(step === null ? 0 : step + 1)}
                aria-label="看下一笔"
              >
                下一笔 →
              </button>
              <button className="quiet" onClick={() => showStep(null)}>
                看完整字形
              </button>
            </div>
          </details>
          <div className="writing-instruction" aria-live="polite">
            <strong>
              {active ? `第 ${step! + 1} / ${steps.length} 笔` : `${steps.length} 笔 · 完整字形`}
            </strong>
            <p>{active ? active.stroke.instruction : catalog.ui.full}</p>
            <VoiceButton
              id={active?.audioId ?? 'writing-ui-full'}
              voice={voice}
              label="听当前步骤"
            />
          </div>
          {target.tone ? (
            <div className="writing-placement">
              <p>{target.note}</p>
              <VoiceButton id={`writing-${target.id}-tone`} voice={voice} label="听标调方法" />
            </div>
          ) : (
            <div className="writing-placement">
              {(active ? [active.glyphId] : [...new Set(target.glyphIds)]).map((id) => (
                <div key={id}>
                  <p>
                    {catalog.glyphs[id]!.symbol} · {catalog.glyphs[id]!.placement}
                  </p>
                  <VoiceButton
                    id={`writing-${id}-placement`}
                    voice={voice}
                    label={`听${catalog.glyphs[id]!.symbol}占格`}
                  />
                </div>
              ))}
            </div>
          )}
          {activeGlyph && !target.tone && (
            <span className="screen-reader-only">{activeGlyph.description}</span>
          )}
          <div className="writing-paper">
            <span aria-hidden="true">✎ ▤</span>
            <p>拿出纸笔，慢慢写一写</p>
            <VoiceButton id="writing-ui-paper" voice={voice} label="听纸笔练习" />
            <small>可以随时停下来。这项练习不打分。</small>
          </div>
        </>
      )}
      <VoiceFailure voice={voice} />
    </section>
  );
}
