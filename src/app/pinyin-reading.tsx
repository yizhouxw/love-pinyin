import { alignPhonetics } from '../domain/phonetic-alignment';
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

/** Every syllable and its character share one measurable, unbreakable column. */
export function PhoneticText({
  text,
  pinyin,
  primary = 'hanzi',
  concealHanzi = false,
  activeIndex = -1,
}: {
  text: string;
  pinyin: string;
  primary?: 'hanzi' | 'pinyin';
  concealHanzi?: boolean;
  activeIndex?: number;
}) {
  const units = alignPhonetics(text, pinyin);
  if (!units)
    return (
      <span className="phonetic-fallback" data-alignment="unmatched">
        <span>
          <PinyinText value={pinyin} />
        </span>
        <span hidden={concealHanzi}>{text}</span>
      </span>
    );
  return (
    <span
      className={`hanzi-pinyin hanzi-pinyin-${primary}`}
      data-alignment="paired"
      data-hanzi={text}
    >
      {units.map((unit, index) => (
        <ruby key={index} className={unit.after ? 'phonetic-punctuation' : ''}>
          <span
            className="phonetic-hanzi"
            style={concealHanzi ? { visibility: 'hidden' } : undefined}
            aria-hidden={concealHanzi}
          >
            {unit.before && <span className="phonetic-before">{unit.before}</span>}
            <span className="phonetic-character">{unit.hanzi}</span>
            {unit.after && <span className="phonetic-after">{unit.after}</span>}
          </span>
          <rt
            data-phonetic-syllable
            className={activeIndex === index ? 'daily-highlight' : undefined}
            aria-current={activeIndex === index ? 'true' : undefined}
          >
            <PinyinText value={unit.pinyin} />
          </rt>
        </ruby>
      ))}
    </span>
  );
}
