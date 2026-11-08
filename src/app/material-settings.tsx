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
  return (
    <details>
      <summary>高级设置</summary>
      {packs?.household ? (
        <label>
          学习素材
          <select
            value={source}
            disabled={busy}
            onChange={(event) =>
              onChange(event.target.value === 'household' ? 'household' : 'original')
            }
          >
            <option value="original">新版原创素材</option>
            <option value="household">旧版家庭素材</option>
          </select>
        </label>
      ) : (
        <p>{packs ? '此版本使用新版原创素材。' : '正在读取学习素材。'}</p>
      )}
      {source === 'original' &&
        packs?.standardSources.map((item) => (
          <p key={item.url}>
            {item.attribution} · {item.license} · {item.licenseUrl}
          </p>
        ))}
    </details>
  );
}
