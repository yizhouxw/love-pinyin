import { useState } from 'react';
import type { Bootstrap } from '../domain/learning-api';
import { api } from '../platform/api-client';
import { suggestedDeviceModel } from '../platform/device-info';
import { startGuest } from '../platform/guest';
import { CopyCode } from './copy-code';
import { Notice } from './notice';

export function PairingPage({
  boot,
  busy,
  act,
  refresh,
  error,
}: {
  boot: Bootstrap;
  busy: boolean;
  act: (work: () => Promise<void>) => Promise<void>;
  refresh: () => Promise<void>;
  error: string;
}) {
  const [code, setCode] = useState('');
  const [pairCode, setPairCode] = useState('');
  const [deviceModel, setDeviceModel] = useState(suggestedDeviceModel);
  return (
    <main className="pair-page">
      <header className="brand">
        <span className="brand-mark">拼</span>
        <span>爱拼音</span>
      </header>
      <section className="hero-card">
        <div className="hero-orbit" aria-hidden="true">
          ā
        </div>
        <p className="eyebrow">陪孩子慢慢学 · 每次几分钟</p>
        <h1>
          拼音小岛
          <br />
          等你来探索
        </h1>
        <p>在这台 Mac Studio 上运行的家庭学习空间。配对后，学习记录只保存在这台电脑里。</p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void act(async () => {
              await api('/pair', {
                method: 'POST',
                body: JSON.stringify({ code, label: '学习设备', model: deviceModel }),
              });
              setCode('');
              await refresh();
            });
          }}
        >
          <label htmlFor="pair-device-model">设备型号（可修改）</label>
          <input
            id="pair-device-model"
            value={deviceModel}
            maxLength={80}
            onChange={(event) => setDeviceModel(event.target.value)}
            placeholder="例如：iPad Air 5"
          />
          <label htmlFor="pair-code">家长配对码</label>
          <div className="pair-input">
            <input
              id="pair-code"
              value={code}
              onChange={(event) => setCode(event.target.value.toUpperCase())}
              maxLength={12}
              autoComplete="one-time-code"
            />
            <button disabled={busy || code.length < 8}>连接家庭</button>
          </div>
        </form>
        <div className="local-pair">
          <h2>没有配对码？</h2>
          {boot.isLocalHost ? (
            <>
              <button
                className="quiet"
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    const result = await api('/local/pairing-code', { method: 'POST' });
                    setPairCode(result.code);
                    setCode(result.code);
                  })
                }
              >
                在 Mac 上生成家长配对码
              </button>
              {pairCode && (
                <div className="pair-code">
                  {pairCode}
                  <CopyCode key={pairCode} code={pairCode} label="新生成的配对码" />
                  <small>5 分钟内一次有效</small>
                </div>
              )}
            </>
          ) : (
            <p>
              请在服务器 Mac 上打开 <strong>http://127.0.0.1:8000</strong>，点击“在 Mac
              上生成家长配对码”； 或在服务器 Mac 本机的“家长管理”中生成配对码，再回到这里输入。
            </p>
          )}
        </div>
        <div className="local-pair">
          <button
            className="guest-start"
            disabled={busy}
            onClick={() =>
              void act(async () => {
                startGuest();
                window.location.reload();
              })
            }
          >
            访客体验
          </button>
          <p>
            无需配对。进度仅缓存在当前标签页，刷新可继续；退出会清除，不跨设备同步。仍需连接家庭
            Mac。
          </p>
        </div>
        <p className="privacy-note">
          🔒 课程练习不使用麦克风。每日跟读可自愿录音，电脑本地识别，不保存。
        </p>
      </section>
      <Notice error={error} onReconnect={() => void act(refresh)} />
    </main>
  );
}
