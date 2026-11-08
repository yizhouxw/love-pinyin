import { useState } from 'react';
import { PinyinText } from './pinyin-reading';
import catalog from '../../content/word-practice/images.json';

export function WordImage({
  word,
  concealed = false,
}: {
  word: { text: string; pinyin: string };
  concealed?: boolean;
}) {
  const [retry, setRetry] = useState(0);
  const [failed, setFailed] = useState<string | null>(null);
  const item = (
    catalog.items as Record<string, { id: string; description: string; sha256: string }>
  )[word.text];
  return (
    <figure
      className="word-selected-picture"
      aria-label={concealed ? '听写未揭晓' : `${item ? '词语图片' : '词语'}：${word.text}`}
    >
      {item && (
        <div className="word-image-frame">
          <img
            key={`${word.text}:${retry}`}
            className={concealed ? 'word-invisible' : ''}
            aria-hidden={concealed}
            src={`/word-illustrations/${item.id}.svg?v=${item.sha256.slice(0, 12)}${retry ? `&retry=${retry}` : ''}`}
            alt={concealed ? '' : item.description}
            width="360"
            height="240"
            onLoad={() => setFailed(null)}
            onError={() => setFailed(`${word.text}:${retry}`)}
          />
          {concealed ? (
            <span className="word-image-concealed">听一听，写好再揭晓</span>
          ) : (
            failed === `${word.text}:${retry}` && (
              <div className="word-image-failure">
                <span>图片暂时打不开</span>
                <button
                  onClick={() => {
                    setRetry(retry + 1);
                    setFailed(null);
                  }}
                >
                  重试图片
                </button>
              </div>
            )
          )}
        </div>
      )}
      <figcaption>
        <ruby className={concealed ? 'word-invisible' : ''} aria-hidden={concealed}>
          {word.text}
          <rt>
            <PinyinText value={word.pinyin} />
          </rt>
        </ruby>
        {item && (
          <small className={concealed ? 'word-invisible' : ''} aria-hidden={concealed}>
            情景示意
          </small>
        )}
        {concealed && <span className="word-caption-concealed">答案未揭晓</span>}
      </figcaption>
    </figure>
  );
}
