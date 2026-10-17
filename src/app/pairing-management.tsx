import { useCallback, useEffect, useState } from 'react';
import type { Bootstrap } from '../domain/learning-api';
import { suggestedDeviceModel } from '../platform/device-info';
import { isGuest, leaveGuest } from '../platform/guest';
import { householdApi } from '../platform/api-client';
import { CopyCode } from './copy-code';

export function PairingManagement() {
  const [access, setAccess] = useState<Bootstrap | null>(null);
  const [code, setCode] = useState('');
  const [deviceModel, setDeviceModel] = useState(suggestedDeviceModel);
  const [generated, setGenerated] = useState('');
  const [expiresAt, setExpiresAt] = useState(0);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [showHelp, setShowHelp] = useState(false);
  const guest = isGuest();
  const loadAccess = useCallback(async () => {
    setAccess((await householdApi('/bootstrap')) as Bootstrap);
  }, []);
  useEffect(() => {
    let cancelled = false;
    void householdApi('/bootstrap')
      .then((value) => {
        if (!cancelled) setAccess(value as Bootstrap);
      })
      .catch(() => {
        if (!cancelled) setError('无法读取配对状态，请检查 Mac 服务后重试。');
      });
    return () => {
      cancelled = true;
    };
  }, []);
  useEffect(() => {
    if (!expiresAt) return;
    const timer = window.setTimeout(() => setExpired(true), Math.max(0, expiresAt - Date.now()));
    return () => window.clearTimeout(timer);
  }, [expiresAt]);
  const canGenerate = Boolean(access?.isLocalHost);
  async function generate() {
    setBusy(true);
    setError('');
    try {
      const result = await householdApi(
        access?.isLocalHost ? '/local/pairing-code' : '/pairing-codes',
        { method: 'POST' },
      );
      setGenerated(result.code);
      setCode(result.code);
      setExpired(false);
      setExpiresAt(Date.now() + result.expiresInSeconds * 1000);
    } catch {
      setError('配对码生成失败，请检查连接并重试；远程生成需要有效的家长权限。');
    } finally {
      setBusy(false);
    }
  }
  async function connect() {
    setBusy(true);
    setError('');
    try {
      await householdApi('/pair', {
        method: 'POST',
        body: JSON.stringify({
          code: code.trim().toUpperCase(),
          label: '学习设备',
          model: deviceModel,
        }),
      });
      leaveGuest();
    } catch (cause) {
      setError(
        cause instanceof Error && cause.message === 'PAIRING_CODE_INVALID'
          ? '配对码无效、已使用或已过期，请重新生成。访客记录仍然保留。'
          : '连接家庭失败，请检查 Mac 连接后重试。访客记录仍然保留。',
      );
      setBusy(false);
    }
  }
  return (
    <section className="parent-panel pairing-management" aria-label="配对码管理">
      <h2>配对码管理</h2>
      <p>
        当前：
        {guest
          ? '访客模式'
          : access?.device?.isParent
            ? '家庭模式 · 家长设备'
            : '家庭模式 · 学习设备'}
      </p>
      {canGenerate ? (
        <>
          <p>生成一次性配对码，在 iPad 或另一台家庭设备上输入即可连接家庭。</p>
          <button className="quiet" disabled={busy} onClick={() => void generate()}>
            生成配对码
          </button>
        </>
      ) : (
        <>
          <p>请在服务器 Mac 的本机入口生成配对码，或由服务器 Mac 的本机家长入口生成。</p>
          <button className="quiet" onClick={() => setShowHelp(true)}>
            如何在 Mac 上生成配对码
          </button>
          {showHelp && (
            <p>
              在服务器 Mac 打开{' '}
              <a href="http://127.0.0.1:8000/" target="_blank" rel="noreferrer">
                http://127.0.0.1:8000/
              </a>
              ，进入家长管理的“配对码管理”；未连接时可直接点“在 Mac 上生成家长配对码”。iPad 上的
              127.0.0.1 指向 iPad，请在 Mac 上操作。
            </p>
          )}
          {!access && (
            <button
              className="quiet"
              onClick={() =>
                void loadAccess()
                  .then(() => setError(''))
                  .catch(() => setError('无法读取配对状态，请检查 Mac 服务后重试。'))
              }
            >
              重新检查配对权限
            </button>
          )}
        </>
      )}
      {generated && (
        <div className="pair-code">
          {generated}
          <CopyCode key={generated} code={generated} label="新生成的配对码" />
          <small role="status">{expired ? '已过期，请重新生成' : '5 分钟内一次有效'}</small>
        </div>
      )}
      {guest && (
        <>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void connect();
            }}
          >
            <label htmlFor="managed-device-model">设备型号（可修改）</label>
            <input
              id="managed-device-model"
              value={deviceModel}
              maxLength={80}
              onChange={(event) => setDeviceModel(event.target.value)}
              placeholder="例如：iPad Air 5"
            />
            <label htmlFor="managed-pair-code">家长配对码</label>
            <div className="pair-input">
              <input
                id="managed-pair-code"
                value={code}
                onChange={(event) => setCode(event.target.value.toUpperCase())}
                maxLength={12}
                autoComplete="one-time-code"
              />
              <button disabled={busy || code.trim().length < 8}>连接家庭</button>
            </div>
          </form>
          <p>连接成功后进入家庭档案，清除本次访客记录，不会将临时进度合并到家庭。</p>
          <button className="quiet" disabled={busy} onClick={leaveGuest}>
            清除并退出访客
          </button>
        </>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
