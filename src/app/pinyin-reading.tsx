import { isWholeSyllable, type ReadingMode } from '../domain/pinyin-spelling';
import './pinyin-reading.css';

export function ReadingModeControl({
  mode,
  onChange,
  disabled,
}: {
  mode: ReadingMode;
  onChange: (mode: ReadingMode) => void;
  disabled?: boolean;
}) {
  return (
    <div className="reading-mode-control" role="group" aria-label="朗读模式">
      <button
        type="button"
        disabled={disabled}
        aria-pressed={mode === 'direct'}
        onClick={() => onChange('direct')}
      >
        直接读
      </button>
      <button
        type="button"
        disabled={disabled}
        aria-pressed={mode === 'spelling'}
        onClick={() => onChange('spelling')}
      >
        拼读
      </button>
    </div>
  );
}

export function PinyinLegend() {
  return (
    <p className="pinyin-legend">
      <span className="pinyin-whole" aria-hidden="true">
        yī
      </span>
      蓝色下划线表示整体认读，直接读出整个音节。
    </p>
  );
}

export function PinyinText({ value }: { value: string }) {
  return value.split(/([\s'’·-]+)/u).map((token, index) =>
    isWholeSyllable(token) ? (
      <span className="pinyin-whole" key={index}>
        {token}
      </span>
    ) : (
      token
    ),
  );
}
