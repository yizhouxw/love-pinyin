import { useEffect, useState } from 'react';
import iosModel from '../../content/qwen-asr.json';
import { householdApi } from '../platform/api-client';
import { iosModelStatus, type IOSModelStatus } from '../platform/audio/ios-recognition';
import { isIOSApp } from '../platform/ios-app';

const iosSize = (
  Object.values(iosModel.files).reduce((bytes, file) => bytes + file.bytes, 0) / 1e9
).toFixed(2);

function requestStatus(download = false): Promise<IOSModelStatus> {
  return isIOSApp()
    ? iosModelStatus(download)
    : householdApi('/local/recognition-model', { method: download ? 'POST' : 'GET' }).then(
        (result) => ({ state: String(result.state) }),
      );
}

export function ModelSettings() {
  const [{ state, bytes, received }, setStatus] = useState<IOSModelStatus>({ state: 'loading' });
  const ios = isIOSApp();
  useEffect(() => {
    let active = true;
    const refresh = () => {
      void requestStatus()
        .then((result) => {
          if (active) setStatus(result);
        })
        .catch(() => {
          if (active) setStatus({ state: 'unavailable' });
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
          {ios
            ? `可选 Qwen3-ASR 0.6B，约 ${iosSize} GB。下载后在这台设备上离线识别。不下载时使用人工确认。`
            : '可选 Qwen3-ASR 0.6B，约 1.01 GB。下载后在这台电脑上为天天练和拼音小卖部识别读音。不下载时使用人工确认。'}
        </p>
        <p role="status">
          {state === 'installed'
            ? '模型已安装'
            : state === 'downloading'
              ? `正在下载并校验${bytes && received ? ` · ${Math.floor((received / bytes) * 100)}%` : ''}，请保持应用运行…`
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
            setStatus({ state: 'downloading' });
            void requestStatus(true)
              .then(setStatus)
              .catch(() => setStatus({ state: 'failed' }));
          }}
        >
          {state === 'failed' ? '重试下载' : '下载模型'}
        </button>
      )}
    </section>
  );
}
