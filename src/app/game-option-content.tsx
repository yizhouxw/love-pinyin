import type { IllustrationCatalog } from '../domain/illustrations';
import { pinyinTone, splitPinyinCandidate } from '../domain/pinyin-presentation';
import type { WritingCatalog, WritingOption } from '../domain/writing';
import { Picture } from './illustrations';
import { WritingChoice } from './writing';

export function GameOptionContent({
  type,
  label,
  initials,
  writing,
  writingCatalog,
  pictureId,
  illustrations,
  pictureKey,
  pictureRetry,
  onPictureStatus,
}: {
  type: string;
  label: string;
  initials: string[];
  writing?: WritingOption;
  writingCatalog?: WritingCatalog;
  pictureId?: string;
  illustrations?: IllustrationCatalog;
  pictureKey?: string;
  pictureRetry?: number;
  onPictureStatus?: (id: string, ready: boolean) => void;
}) {
  if (pictureId)
    return (
      <Picture
        key={pictureKey}
        id={pictureId}
        catalog={illustrations}
        retry={pictureRetry}
        onStatus={(ready) => onPictureStatus?.(pictureId, ready)}
      />
    );
  if (writing) return <WritingChoice catalog={writingCatalog} value={writing} />;
  if (type === 'blend-choice') {
    const parts = splitPinyinCandidate(label, initials);
    return (
      <span className="blend-choice-content">
        {parts ? (
          <span className="blend-pieces" aria-hidden="true">
            <span className="blend-piece">
              <small>拼音开头</small>
              <strong>{parts.onset}</strong>
            </span>
            <span className="blend-join">＋</span>
            <span className="blend-piece">
              <small>韵母</small>
              <strong>{parts.rime}</strong>
            </span>
          </span>
        ) : (
          <span className="blend-whole" aria-hidden="true">
            {label}
          </span>
        )}
        <span className="screen-reader-only">拼读候选 {label}</span>
      </span>
    );
  }
  if (type === 'tone-choice') {
    const tone = pinyinTone(label);
    const paths: Record<number, string> = {
      1: 'M5 12 L35 12',
      2: 'M5 27 L35 10',
      3: 'M5 13 Q20 33 35 13',
      4: 'M5 10 L35 28',
    };
    return (
      <span className="tone-choice-content">
        {tone && (
          <svg aria-hidden="true" viewBox="0 0 40 38" className="tone-contour">
            <path d={paths[tone]} />
          </svg>
        )}
        <span className="tone-choice-label">{label}</span>
      </span>
    );
  }
  if (
    type === 'symbol-choice' &&
    [...label].length <= 3 &&
    /^[a-züāáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜ]+$/u.test(label)
  ) {
    return (
      <span className="symbol-card-content">
        <span className="four-line-card" aria-hidden="true">
          {label}
        </span>
        <span className="screen-reader-only">拼音字形 {label}</span>
      </span>
    );
  }
  return <span className="plain-option-label">{label}</span>;
}
