import { useState } from 'react';
import playback from '../../content/playback.json';

export function PlaybackGapControl({
  seconds,
  disabled,
  onSave,
}: {
  seconds: number;
  disabled: boolean;
  onSave: (seconds: number) => void;
}) {
  const [draft, setDraft] = useState(String(seconds));
  const value = Number(draft);
  const valid =
    draft !== '' &&
    Number.isFinite(value) &&
    value >= playback.gap.minSeconds &&
    value <= playback.gap.maxSeconds &&
    Math.abs(value * 10 - Math.round(value * 10)) < 1e-8;
  return (
    <div className="parent-setting">
      <div>
        <strong>连播间隔</strong>
        <p>两个读音或两条示范之间的等待时间。默认1秒，可设置0.1～5秒，每次调节0.1秒。</p>
      </div>
      <div className="playback-gap-control">
        <label>
          连播间隔（秒）
          <input
            type="number"
            min={playback.gap.minSeconds}
            max={playback.gap.maxSeconds}
            step={playback.gap.stepSeconds}
            value={draft}
            disabled={disabled}
            onChange={(event) => setDraft(event.target.value)}
          />
        </label>
        <button
          className="quiet"
          disabled={disabled || !valid || value === seconds}
          onClick={() => onSave(value)}
        >
          保存间隔
        </button>
        {!valid && <p role="alert">请输入0.1～5秒之间的值，精度为0.1秒。</p>}
        <small>当前间隔：{seconds.toFixed(1)}秒</small>
      </div>
    </div>
  );
}
