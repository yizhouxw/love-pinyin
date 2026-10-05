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
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const items = Object.entries(catalog.items).filter(([, item]) => item.lessonId === lessonId);
  if (!items.length) return null;
  return (
    <section className="word-cards" aria-label="生活里的拼音">
      <div className="word-heading">
        <h3>生活里的拼音</h3>
        <VoiceButton id="picture-intro" voice={voice} label="听看图玩法" />
      </div>
      {items.map(([id, item]) => (
        <div key={id} className="word-card">
          <figure>
            <Picture
              key={`${id}-${retry}`}
              id={id}
              catalog={catalog}
              retry={retry}
              onStatus={(ready) => setFailed(!ready)}
            />
            <figcaption>
              <span>{item.pinyin}</span>
              <small>{item.name}</small>
            </figcaption>
          </figure>
          <div>
            <VoiceButton id={item.audioRef} kind="standard" voice={voice} label="听这个拼音" />
            <VoiceButton id={`picture-${id}`} voice={voice} label="听图片说明" />
          </div>
        </div>
      ))}
      {failed && (
        <div className="picture-failure" role="alert">
          <p>图片暂时没加载好，可以重试。</p>
          <button
            className="quiet"
            onClick={() => {
              setFailed(false);
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
