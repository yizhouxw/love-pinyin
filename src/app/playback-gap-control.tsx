import { useId, useState, type CSSProperties } from 'react';
import playback from '../../content/playback.json';
import { readingGapSeconds, type DailyItem } from '../domain/daily-reading';

export function PlaybackGapControl({
  seconds,
  disabled,
  onSave,
  deviceOnly = false,
  guest = false,
  item,
  onCancel,
}: {
  seconds: number;
  disabled: boolean;
  onSave: (seconds: number) => void;
  deviceOnly?: boolean;
  guest?: boolean;
  item?: DailyItem;
  onCancel?: () => void;
}) {
  const [draft, setDraft] = useState(String(seconds));
  const errorId = useId();
  const value = Number(draft);
  const valid =
    draft !== '' &&
    Number.isFinite(value) &&
    value >= playback.gap.minSeconds &&
    value <= playback.gap.maxSeconds &&
    Math.abs(value * 10 - Math.round(value * 10)) < 1e-8;
  const preview = valid ? value : seconds;
  const percent =
    ((preview - playback.gap.minSeconds) / (playback.gap.maxSeconds - playback.gap.minSeconds)) *
    100;
  function adjust(direction: -1 | 1) {
    const next = Math.round((preview + direction * playback.gap.stepSeconds) * 10) / 10;
    setDraft(String(Math.max(playback.gap.minSeconds, Math.min(playback.gap.maxSeconds, next))));
  }
  return (
    <div className={deviceOnly ? 'playback-gap-editor' : 'parent-setting playback-setting'}>
      {!deviceOnly && (
        <div className="playback-setting-heading">
          <strong>连播间隔</strong>
          <p>给孩子留一点时间，听完再跟读。</p>
        </div>
      )}
      <div className="playback-gap-controls">
        <div className="gap-presets" role="group" aria-label="选择跟读节奏">
          {playback.gap.presets.map((preset) => (
            <button
              key={preset.seconds}
              type="button"
              tabIndex={0}
              disabled={disabled}
              aria-pressed={valid && value === preset.seconds}
              aria-label={`${preset.label} ${preset.seconds.toFixed(1)}秒`}
              onClick={() => setDraft(String(preset.seconds))}
            >
              <strong>{preset.label}</strong>
              <span>{preset.seconds.toFixed(1)}秒</span>
            </button>
          ))}
        </div>
        <div className="gap-stepper">
          <button
            className="gap-step-button"
            type="button"
            tabIndex={0}
            aria-label="减少0.1秒"
            disabled={disabled || preview <= playback.gap.minSeconds}
            onClick={() => adjust(-1)}
          >
            <span aria-hidden="true">−</span>
          </button>
          <label className="gap-number">
            <span>基础间隔</span>
            <span className="gap-number-value">
              <input
                type="number"
                aria-label="连播间隔（秒）"
                aria-invalid={!valid}
                aria-describedby={!valid ? errorId : undefined}
                inputMode="decimal"
                min={playback.gap.minSeconds}
                max={playback.gap.maxSeconds}
                step={playback.gap.stepSeconds}
                value={draft}
                disabled={disabled}
                onChange={(event) => setDraft(event.target.value)}
              />
              <span>秒</span>
            </span>
          </label>
          <button
            className="gap-step-button"
            type="button"
            tabIndex={0}
            aria-label="增加0.1秒"
            disabled={disabled || preview >= playback.gap.maxSeconds}
            onClick={() => adjust(1)}
          >
            <span aria-hidden="true">＋</span>
          </button>
        </div>
        <input
          className="gap-range"
          type="range"
          aria-label="调节基础间隔"
          aria-valuetext={`${preview.toFixed(1)}秒`}
          min={playback.gap.minSeconds}
          max={playback.gap.maxSeconds}
          step={playback.gap.stepSeconds}
          value={preview}
          disabled={disabled}
          style={{ '--gap-progress': `${percent}%` } as CSSProperties}
          onChange={(event) => setDraft(event.target.value)}
        />
        <div className="gap-range-labels" aria-hidden="true">
          <span>{playback.gap.minSeconds}秒</span>
          <span>{playback.gap.maxSeconds}秒</span>
        </div>
        {!valid && (
          <p className="gap-error" id={errorId} role="alert">
            请输入0.1～5秒，最多一位小数。
          </p>
        )}
        <div className="gap-preview" aria-live="polite">
          {item ? (
            <p>
              这条读完后，留<strong>{readingGapSeconds(item, preview).toFixed(1)}秒</strong>跟读
            </p>
          ) : (
            <p>词句越长，留给你跟读的时间越多。</p>
          )}
        </div>
        <p className="gap-scope">
          {deviceOnly
            ? guest
              ? '仅当前访客标签页生效，退出后清除。'
              : '仅本浏览器生效，家长更改默认值后同步更新。'
            : guest
              ? '作为当前访客的默认间隔，退出后清除。'
              : '家庭默认间隔，学生可在练习页单独调整。'}
        </p>
        {disabled && deviceOnly && <p className="gap-scope">录音或识别结束后可以调整。</p>}
        <div className="gap-editor-actions">
          {onCancel && (
            <button type="button" className="quiet" tabIndex={0} onClick={onCancel}>
              取消
            </button>
          )}
          <button
            type="button"
            className="gap-apply"
            tabIndex={0}
            disabled={disabled || !valid || value === seconds}
            onClick={() => onSave(value)}
          >
            {deviceOnly ? '应用间隔' : '保存间隔'}
          </button>
        </div>
        {!deviceOnly && <small className="gap-saved">当前间隔：{seconds.toFixed(1)}秒</small>}
      </div>
    </div>
  );
}
