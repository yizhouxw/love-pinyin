import { useState } from 'react';
import playback from '../../content/playback.json';

export function PlaybackGapControl({
  seconds,
  disabled,
  onSave,
  deviceOnly = false,
  guest = false,
}: {
  seconds: number;
  disabled: boolean;
  onSave: (seconds: number) => void;
  deviceOnly?: boolean;
  guest?: boolean;
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
        <strong>{deviceOnly ? '本设备的基础间隔' : '连播基础间隔'}</strong>
        <p>
          词句之间按长度等待：基础间隔加上每多一个音节
          {playback.reading.extraSecondsPerSyllable}秒。词内紧凑接续，不使用此间隔。默认
          {playback.gap.defaultSeconds}秒，可设置{playback.gap.minSeconds}～
          {playback.gap.maxSeconds}秒。
        </p>
        <p>
          {deviceOnly
            ? guest
              ? '只在当前访客标签页记住，退出访客后清除。保存会停止当前示范，再点连播即可使用新间隔。'
              : '只在本浏览器记住；家长更改默认间隔后采用新的默认值。保存会停止当前示范，再点连播即可使用新间隔。'
            : guest
              ? '作为当前访客练习的默认值，退出访客后清除。练习页也可快捷调整。'
              : '作为学习设备的默认值，学生练习页也可单独调整本设备的间隔。'}
        </p>
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
          tabIndex={0}
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
