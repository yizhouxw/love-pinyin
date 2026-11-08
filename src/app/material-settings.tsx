import type { PracticePacks, PracticeSource } from '../domain/practice-packs';

export function MaterialSettings({
  source,
  onChange,
  busy,
}: {
  source: PracticeSource;
  onChange: (source: PracticeSource) => void;
  busy: boolean;
}) {
  return (
    <details className="parent-section material-settings">
      <summary>高级设置</summary>
      <div className="parent-setting material-setting">
        <div>
          <strong>学习素材</strong>
          <p>影响课堂讲解、标准音和两类天天练。</p>
        </div>
        <select
          aria-label="学习素材"
          value={source}
          disabled={busy}
          onChange={(event) =>
            onChange(event.target.value === 'household' ? 'household' : 'original')
          }
        >
          <option value="original">新版素材</option>
          <option value="household">旧版家庭素材</option>
        </select>
      </div>
    </details>
  );
}

export function MaterialInfo({ packs }: { packs: PracticePacks }) {
  return (
    <>
      {!packs.household && <p>学习素材：新版素材</p>}
      {packs.standardSources.length > 0 && (
        <details className="parent-section material-credits">
          <summary>音频来源与许可</summary>
          <p>新版声母、韵母、带调音节及词语拼读的单音示范使用大陆普通话录音。</p>
          <ul>
            {packs.standardSources.map((item) => (
              <li key={item.url}>
                <strong>{item.license}</strong>
                <p>{item.attribution}</p>
                <small>{item.licenseUrl}</small>
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
