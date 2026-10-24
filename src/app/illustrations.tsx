import { useState } from 'react';
import type { IllustrationCatalog } from '../domain/illustrations';
import { useLearningVoice, VoiceButton, VoiceFailure } from './learning-voice';

export function Picture({
  id,
  catalog,
  retry = 0,
  onStatus,
}: {
  id: string;
  catalog?: IllustrationCatalog;
  retry?: number;
  onStatus?: (ready: boolean) => void;
}) {
  const item = catalog?.items[id];
  if (!item || !/^v[0-9]+-[a-z]+$/.test(id)) return <span>图片未加载，请重新连接</span>;
  return (
    <img
      className="word-picture"
      src={`/illustrations/${id}.svg${retry ? `?retry=${retry}` : ''}`}
      onLoad={() => onStatus?.(true)}
      onError={() => onStatus?.(false)}
      alt={item.description}
      width="240"
      height="180"
    />
  );
}

export function WordCards({
  catalog,
  lessonId,
}: {
  catalog: IllustrationCatalog;
  lessonId: string;
}) {
  const voice = useLearningVoice(`pictures-${lessonId}`);
  const [imageFailures, setImageFailures] = useState<{
    lesson: string;
    ids: Set<string>;
    retry: number;
  }>({ lesson: lessonId, ids: new Set(), retry: 0 });
  const [retry, setRetry] = useState(0);
  const [index, setIndex] = useState(0);
  const items = Object.entries(catalog.items).filter(([, item]) => item.lessonId === lessonId);
  const failed =
    imageFailures.lesson === lessonId &&
    imageFailures.retry === retry &&
    imageFailures.ids.has(items[index]?.[0] ?? '');
  if (!items.length) return null;
  return (
    <section className="word-cards" aria-label="生活里的拼音">
      <div className="word-heading">
        <h3>生活里的拼音</h3>
        <VoiceButton id="picture-intro" voice={voice} label="听看图玩法" />
      </div>
      <div className="picture-navigation" role="group" aria-label="浏览生活图片">
        <button
          className="quiet"
          disabled={index === 0}
          onClick={() => {
            voice.stop();
            setIndex(index - 1);
          }}
        >
          ← 上一张
        </button>
        <span aria-live="polite">
          {index + 1} / {items.length}
        </span>
        <button
          className="quiet"
          disabled={index === items.length - 1}
          onClick={() => {
            voice.stop();
            setIndex(index + 1);
          }}
        >
          下一张 →
        </button>
      </div>
      <div className="word-card-grid">
        {items.slice(index, index + 1).map(([id, item]) => (
          <div key={id} className="word-card">
            <figure>
              <Picture
                key={`${id}-${retry}`}
                id={id}
                catalog={catalog}
                retry={retry}
                onStatus={(ready) =>
                  setImageFailures((previous) => {
                    const ids = new Set(
                      previous.lesson === lessonId && previous.retry === retry ? previous.ids : [],
                    );
                    if (ready) ids.delete(id);
                    else ids.add(id);
                    return { lesson: lessonId, ids, retry };
                  })
                }
              />
              <figcaption>
                <span>{item.pinyin}</span>
                <small>{item.name}</small>
                {item.associationNote && (
                  <small className="word-association-note">{item.associationNote}</small>
                )}
              </figcaption>
            </figure>
            <div>
              <VoiceButton
                id={item.audioRef}
                kind={item.audioKind ?? 'standard'}
                voice={voice}
                label="听这个拼音"
              />
              <VoiceButton id={`picture-${id}`} voice={voice} label="听图片说明" />
            </div>
          </div>
        ))}
      </div>
      {failed && (
        <div className="picture-failure" role="alert">
          <p>图片暂时没加载好，可以重试。</p>
          <button
            className="quiet"
            onClick={() => {
              setImageFailures({ lesson: lessonId, ids: new Set(), retry: retry + 1 });
              setRetry((n) => n + 1);
            }}
          >
            ↻ 重试图片
          </button>
          <VoiceButton id="picture-error" voice={voice} label="听图片提示" />
        </div>
      )}
      <VoiceFailure voice={voice} />
    </section>
  );
}
