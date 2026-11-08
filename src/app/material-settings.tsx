import type { PracticePacks, PracticeSource } from '../domain/practice-packs';

export function MaterialSettings({
  packs,
  source,
  onChange,
  busy,
}: {
  packs: PracticePacks | null;
  source: PracticeSource;
  onChange: (source: PracticeSource) => void;
  busy: boolean;
}) {
  const label = source === 'original' ? '新版原创素材' : '旧版家庭素材';
  return (
    <details className="parent-section material-settings">
      <summary>高级设置</summary>
      <div className="parent-setting material-setting">
        <div>
          <strong>学习素材</strong>
          <p>影响课堂讲解、标准音和两类天天练。</p>
        </div>
        {packs?.household ? (
          <select
            aria-label="学习素材"
            value={source}
            disabled={busy}
            onChange={(event) =>
              onChange(event.target.value === 'household' ? 'household' : 'original')
            }
          >
            <option value="original">新版原创素材</option>
            <option value="household">旧版家庭素材</option>
          </select>
        ) : (
          <small>{packs ? label : '正在读取学习素材…'}</small>
        )}
      </div>
      {Boolean(packs?.standardSources.length) && (
        <details className="material-credits">
          <summary>音频来源与许可</summary>
          <p>新版声母、韵母、带调音节及词语拼读的单音示范使用大陆普通话录音。</p>
          <ul>
            {packs?.standardSources.map((item) => (
              <li key={item.url}>
                <strong>{item.license}</strong>
                <p>{item.attribution}</p>
                <small>{item.licenseUrl}</small>
              </li>
            ))}
          </ul>
        </details>
      )}
    </details>
  );
}
