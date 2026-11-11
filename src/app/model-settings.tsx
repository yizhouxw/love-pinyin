import { useEffect, useState } from 'react';
import iosModel from '../../content/qwen-asr.json';
import { householdApi } from '../platform/api-client';
import type { IOSModelStatus } from '../platform/audio/ios-recognition';
import { isIOSApp, iosOperation } from '../platform/ios-app';

const iosSize = (
  Object.values(iosModel.files).reduce((bytes, file) => bytes + file.bytes, 0) / 1e9
).toFixed(2);

type Action = 'modelStatus' | 'modelDownload' | 'modelCancel' | 'modelRemove';

function requestStatus(action: Action): Promise<IOSModelStatus> {
  return isIOSApp()
    ? iosOperation<IOSModelStatus>(action)
    : householdApi('/local/recognition-model', {
        method: action === 'modelDownload' ? 'POST' : 'GET',
      }).then((result) => ({ state: String(result.state) }));
}

export function ModelSettings() {
  const [{ state, bytes, received }, setStatus] = useState<IOSModelStatus>({ state: 'loading' });
  const [queryFailed, setQueryFailed] = useState(false);
  const [action, setAction] = useState<Action | null>(null);
  const [actionFailed, setActionFailed] = useState(false);
  const [confirmRemoval, setConfirmRemoval] = useState(false);
  const ios = isIOSApp();

  useEffect(() => {
    if (action) return;
    let active = true;
    let timer: number | undefined;
    let checking = false;
    async function refresh() {
      if (checking) return;
      checking = true;
      window.clearTimeout(timer);
      try {
        const result = await requestStatus('modelStatus');
        if (!active) return;
        setStatus(result);
        setQueryFailed(false);
        if (result.state === 'downloading') timer = window.setTimeout(refresh, 3000);
      } catch {
        if (active) setQueryFailed(true);
      } finally {
        checking = false;
      }
    }
    void refresh();
    window.addEventListener('focus', refresh);
    return () => {
      active = false;
      window.clearTimeout(timer);
      window.removeEventListener('focus', refresh);
    };
  }, [action]);

  async function perform(next: Action) {
    setAction(next);
    setActionFailed(false);
    try {
      setStatus(await requestStatus(next));
      setQueryFailed(false);
    } catch {
      if (next === 'modelStatus') setQueryFailed(true);
      else setActionFailed(true);
    } finally {
      setAction(null);
    }
  }

  return (
    <section className="parent-setting">
      <div>
        <strong>本地语音识别模型</strong>
        <p>
          {ios
            ? `可选 Qwen3-ASR 0.6B，约 ${iosSize} GB。下载后在这台设备上离线识别。`
            : '可选 Qwen3-ASR 0.6B，约 1.01 GB。下载后在这台电脑上为天天练和拼音小卖部识别读音。'}
          不下载时使用人工确认。
        </p>
        <p role="status">
          {actionFailed
            ? '操作没有完成，请检查网络和设备空间后重试。'
            : queryFailed
              ? '暂时无法获取模型状态，仍可使用人工确认。'
              : state === 'loading'
                ? '正在查看模型状态…'
                : state === 'installed'
                  ? '模型已安装'
                  : state === 'downloading'
                    ? `正在下载并校验${bytes && received ? ` · ${Math.floor((received / bytes) * 100)}%` : ''}，请保持应用运行…`
                    : state === 'failed'
                      ? '下载或校验失败，请检查网络和设备空间后重试。'
                      : state === 'unsupported'
                        ? '此设备使用人工确认。'
                        : '模型尚未安装'}
        </p>
      </div>
      {queryFailed ? (
        <button type="button" disabled={!!action} onClick={() => void perform('modelStatus')}>
          重新查看状态
        </button>
      ) : state === 'downloading' && ios ? (
        <button type="button" disabled={!!action} onClick={() => void perform('modelCancel')}>
          停止下载
        </button>
      ) : ios && state === 'installed' ? (
        confirmRemoval ? (
          <div>
            <p>移除后可以继续人工确认，学习记录会保留。</p>
            <button type="button" onClick={() => setConfirmRemoval(false)}>
              保留模型
            </button>
            <button
              type="button"
              disabled={!!action}
              onClick={() => {
                setConfirmRemoval(false);
                void perform('modelRemove');
              }}
            >
              确认移除
            </button>
          </div>
        ) : (
          <button type="button" disabled={!!action} onClick={() => setConfirmRemoval(true)}>
            移除模型并释放空间
          </button>
        )
      ) : ['idle', 'failed'].includes(state) ? (
        <button type="button" disabled={!!action} onClick={() => void perform('modelDownload')}>
          {state === 'failed' || actionFailed ? '重试下载' : '下载模型'}
        </button>
      ) : null}
    </section>
  );
}
