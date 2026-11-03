import { useEffect, useState } from 'react';
import { householdApi } from '../platform/api-client';

export function ModelSettings() {
  const [state, setState] = useState('loading');
  useEffect(() => {
    let active = true;
    const refresh = () => {
      void householdApi('/local/recognition-model')
        .then((result) => {
          if (active) setState(String(result.state));
        })
        .catch(() => {
          if (active) setState('unavailable');
        });
    };
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);
  if (state === 'unavailable') return null;
  return (
    <section className="parent-setting">
      <div>
        <strong>天天练本地识别模型</strong>
        <p>
          可选 Whisper small，约 488
          MB。下载后在这台电脑本地识别，不评判四声；不下载也可听读和练习。
        </p>
        <p role="status">
          {state === 'installed'
            ? '模型已安装'
            : state === 'downloading'
              ? '正在下载并校验，请保持应用运行…'
              : state === 'failed'
                ? '下载或校验失败，请检查网络和磁盘后重试。'
                : '模型尚未安装'}
        </p>
      </div>
      {state !== 'installed' && (
        <button
          type="button"
          disabled={state === 'downloading' || state === 'loading'}
          onClick={() => {
            void householdApi('/local/recognition-model', { method: 'POST' })
              .then((result) => setState(String(result.state)))
              .catch(() => setState('failed'));
          }}
        >
          {state === 'failed' ? '重试下载' : '下载模型'}
        </button>
      )}
    </section>
  );
}
