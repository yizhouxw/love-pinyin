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
        <strong>本地语音识别模型</strong>
        <p>
          可选 Qwen3-ASR 0.6B，约 1.01
          GB。下载后在这台电脑上为天天练和拼音小卖部识别读音。不下载时使用人工确认。
        </p>
        <p role="status">
          {state === 'installed'
            ? '模型已安装'
            : state === 'downloading'
              ? '正在下载并校验，请保持应用运行…'
              : state === 'failed'
                ? '下载或校验失败，请检查网络和磁盘后重试。'
                : state === 'unsupported'
                  ? '此设备使用人工确认。'
                  : '模型尚未安装'}
        </p>
      </div>
      {state !== 'installed' && state !== 'unsupported' && (
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
