import { useCallback, useEffect, useState } from 'react';
import type { LearningAudio } from './learning-voice';
import type { LearningSettingsProps } from './settings-types';
import playback from '../../content/playback.json';
import type { AudioRequirement, Bootstrap, Json, Lesson } from '../domain/learning-api';
import { api } from '../platform/api-client';
import { CopyCode } from './copy-code';
import { KnowledgeProgress } from './knowledge-progress';
import { formatAttemptTime } from './labels';
import { ReducedMotionControl } from './management-controls';
import { PlaybackGapControl } from './playback-gap-control';
import { ReleaseHistory } from './release-history';
import { Notice } from './notice';

export function ParentPanel({
  boot,
  error = '',
  onGuidanceChange,
  curriculum,
  progress,
  lessonChoice,
  setLessonChoice,
  busy,
  refresh,
  act,
  learningAudio,
}: LearningSettingsProps & {
  boot: Bootstrap;
  error?: string;
  onGuidanceChange: (enabled: boolean) => void;
  learningAudio: LearningAudio | null;
}) {
  const [confirm, setConfirm] = useState('');
  const [resetConfirm, setResetConfirm] = useState('');
  const [exportJson, setExportJson] = useState('');
  const [exportRevision, setExportRevision] = useState<number | null>(null);
  const [importPreview, setImportPreview] = useState<Json | null>(null);
  const [importFileName, setImportFileName] = useState('');
  const [importConfirmation, setImportConfirmation] = useState('');
  const [importComplete, setImportComplete] = useState(false);
  const [devices, setDevices] = useState<Json[]>([]);
  const [deviceModels, setDeviceModels] = useState<Record<string, string>>({});
  const [revokeDeviceId, setRevokeDeviceId] = useState('');
  const [deviceError, setDeviceError] = useState('');
  const [clockResolutionConfirm, setClockResolutionConfirm] = useState('');

  const isParent = Boolean(boot.device?.isParent);
  const audioRequirements = (curriculum?.audioRequirements ?? []) as AudioRequirement[];
  const savedLessonExists = curriculum.lessons.some(
    (lesson: Lesson) => lesson.id === progress.selectedLessonId,
  );
  const selectedLessonChoice = lessonChoice || (savedLessonExists ? progress.selectedLessonId : '');
  const reloadDevices = useCallback(async () => {
    const result = await api('/devices');
    setDevices(result.devices as Json[]);
    setDeviceError('');
  }, []);
  useEffect(() => {
    if (!isParent) return;
    let cancelled = false;
    void api('/devices')
      .then((result) => {
        if (!cancelled) setDevices(result.devices as Json[]);
      })
      .catch((reason: Error) => {
        if (!cancelled) setDeviceError(reason.message);
      });
    return () => {
      cancelled = true;
    };
  }, [isParent]);
  return (
    <section className="parent-panel">
      <h2>学习与隐私设置</h2>
      <section className="parent-overview" aria-label="学习概览">
        <p>
          已完成 {progress.completedSessions} 轮练习 · {progress.attemptCount ?? 0} 次作答
        </p>
        <p>
          {(progress.reviewRecommendations?.length ?? 0) > 0
            ? `待复习：${progress.reviewRecommendations?.map((item) => item.symbol).join('、')}。回到学习页可开始复习。`
            : '暂时没有到期复习，按当前课程继续学习即可。'}
        </p>
      </section>
      <div className="parent-setting">
        <div>
          <strong>当前课程</strong>
          <p>
            {savedLessonExists
              ? '孩子只可学习当前课及之前内容。'
              : '已保存的课程不在此版本中；原有进度会保留，请重新选择学校当前课。'}
          </p>
        </div>
        <div className="inline-control">
          <select
            aria-label="当前课程"
            value={selectedLessonChoice}
            disabled={busy}
            onChange={(event) => setLessonChoice(event.target.value)}
          >
            <option value="">请选择当前课程</option>
            {curriculum.lessons.map((lesson: Json) => (
              <option key={lesson.id} value={lesson.id}>
                {lesson.order}. {lesson.title}
              </option>
            ))}
          </select>
          <button
            className="quiet"
            disabled={busy || !isParent || !selectedLessonChoice}
            onClick={() =>
              void act(async () => {
                await api('/household/current-lesson', {
                  method: 'PUT',
                  body: JSON.stringify({
                    lessonId: selectedLessonChoice,
                    expectedRevision: progress.revision,
                  }),
                });
                await refresh();
              })
            }
          >
            保存
          </button>
        </div>
      </div>
      <details className="parent-section">
        <summary>声音与播放设置</summary>
        <section className="parent-audio-status" aria-label="学习音频准备状态">
          <h3>学习音频准备状态</h3>
          <p>
            中文引导：{Object.values(learningAudio?.narration ?? {}).filter(Boolean).length} /{' '}
            {Object.keys(learningAudio?.narration ?? {}).length} 条可播放； 家庭课程录音：
            {
              Object.values(learningAudio?.lessons ?? {}).filter(
                (item) => (item as { available: boolean }).available,
              ).length
            }{' '}
            / {curriculum.lessons.length} 课可播放。
          </p>
          <p>
            中文引导由本地开源模型生成，只读中文操作提示；拼音示范使用独立音频文件。跟读录音留在家庭
            Mac 和浏览器内存中临时处理，不保存。
          </p>
          <p>
            拼音标准音：
            {audioRequirements.filter((asset) => asset.available).length} 项可播放。
            {audioRequirements.some((asset) => asset.standardSource) &&
              '标准音来源：cmguo/PinYinSound，已安装到家庭 Mac。'}
          </p>
          {(!learningAudio ||
            Object.values(learningAudio.narration ?? {}).some((ready) => !ready)) && (
            <p className="audio-error">
              学习音频尚未全部就绪。请在 Mac 项目目录运行 <code>npm run prepare:voice</code>，
              再点重新检查；音频未就绪时不适合孩子独立使用。
            </p>
          )}
          <button className="quiet" disabled={busy} onClick={() => void act(refresh)}>
            重新检查音频
          </button>
        </section>
        <div className="parent-setting">
          <div>
            <strong>自动朗读题目</strong>
            <p>
              开启后，新题、练习反馈和天天练操作说明会自动朗读。关闭后天天练直接播放示范，仍可点喇叭听题；学习页面也可快捷切换。
            </p>
          </div>
          <label>
            <input
              type="checkbox"
              aria-label="自动朗读题目"
              checked={progress.settings?.soundEnabled !== false}
              disabled={!isParent || busy}
              onChange={(event) => {
                const soundEnabled = event.target.checked;
                onGuidanceChange(soundEnabled);
                void act(async () => {
                  await api('/household/settings', {
                    method: 'PUT',
                    body: JSON.stringify({
                      soundEnabled,
                      reducedMotion: Boolean(progress.settings?.reducedMotion),
                    }),
                  });
                  await refresh();
                });
              }}
            />
            开启自动朗读
          </label>
        </div>
        <PlaybackGapControl
          key={progress.settings.playbackGapSeconds ?? playback.gap.defaultSeconds}
          seconds={progress.settings.playbackGapSeconds ?? playback.gap.defaultSeconds}
          disabled={!isParent || busy}
          onSave={(playbackGapSeconds) =>
            void act(async () => {
              await api('/household/settings', {
                method: 'PUT',
                body: JSON.stringify({
                  soundEnabled: progress.settings.soundEnabled !== false,
                  playbackGapSeconds,
                }),
              });
              await refresh();
            })
          }
        />
      </details>
      <details className="parent-section">
        <summary>详细学习记录</summary>
        <KnowledgeProgress curriculum={curriculum} progress={progress} />
      </details>
      {(progress.clockSkewDetected || (progress.pendingClockAttempts ?? 0) > 0) && (
        <div className="parent-setting clock-pending-setting">
          <div>
            <strong>服务器时间与待校时练习</strong>
            <p>
              {progress.clockSkewDetected
                ? 'Mac Studio 时间比先前记录回退超过 5 分钟。请先校准系统时间；期间的新练习不会计入掌握度。'
                : '系统时间已恢复。请决定如何处理待校时练习；保留的记录始终不计入掌握度。'}
            </p>
            <p>待处理练习：{progress.pendingClockAttempts ?? 0} 条</p>
          </div>
          {(progress.pendingClockAttempts ?? 0) > 0 && !progress.clockSkewDetected && (
            <div className="clock-pending-actions">
              <label>
                输入处理方式确认
                <input
                  aria-label="确认处理待校时练习"
                  value={clockResolutionConfirm}
                  onChange={(event) => setClockResolutionConfirm(event.target.value)}
                />
              </label>
              <button
                className="quiet"
                disabled={!isParent || clockResolutionConfirm !== '保留为不计分练习' || busy}
                onClick={() =>
                  void act(async () => {
                    await api('/profiles/clock-pending/resolve', {
                      method: 'POST',
                      body: JSON.stringify({
                        resolution: 'keep-unscored',
                        confirmation: clockResolutionConfirm,
                      }),
                    });
                    setClockResolutionConfirm('');
                    await refresh();
                  })
                }
              >
                保留为不计分练习
              </button>
              <button
                className="danger-button"
                disabled={!isParent || clockResolutionConfirm !== '删除待校时练习' || busy}
                onClick={() =>
                  void act(async () => {
                    await api('/profiles/clock-pending/resolve', {
                      method: 'POST',
                      body: JSON.stringify({
                        resolution: 'discard',
                        confirmation: clockResolutionConfirm,
                      }),
                    });
                    setClockResolutionConfirm('');
                    await refresh();
                  })
                }
              >
                删除待校时练习
              </button>
            </div>
          )}
        </div>
      )}
      <details className="parent-section">
        <summary>显示设置</summary>
        <div className="parent-setting">
          <div>
            <strong>减少动态效果</strong>
            <p>开启后，练习界面停用非必要动画与过渡效果。</p>
          </div>
          <ReducedMotionControl
            key={String(Boolean(progress.settings?.reducedMotion))}
            checked={Boolean(progress.settings?.reducedMotion)}
            disabled={!isParent}
            onChange={(next) =>
              void act(async () => {
                await api('/household/settings', {
                  method: 'PUT',
                  body: JSON.stringify({
                    soundEnabled: Boolean(progress.settings?.soundEnabled),
                    reducedMotion: next,
                  }),
                });
                await refresh();
              })
            }
          />
        </div>
      </details>
      <details className="parent-section">
        <summary>已连接设备</summary>
        {isParent && (
          <div className="device-management">
            <div>
              <strong>已连接设备</strong>
              <button className="quiet" disabled={busy} onClick={() => void act(reloadDevices)}>
                刷新设备列表
              </button>
              <p>撤销后，该设备下次连接时需要重新配对；学习记录会保留。</p>
            </div>
            <ul className="device-list">
              {devices.map((device) => (
                <li key={device.id}>
                  <div>
                    <strong>{device.label}</strong>
                    <small>
                      {device.current ? '本机家长设备' : '家庭设备'} · 配对时间：
                      {formatAttemptTime(device.createdAt)}
                    </small>
                    <p>设备型号：{device.model || '尚未记录，可填写具体型号'}</p>
                    <p>
                      最后连接服务：
                      {device.lastConnectedAt
                        ? formatAttemptTime(device.lastConnectedAt)
                        : '尚未记录'}
                    </p>
                    {device.pairingCode ? (
                      <>
                        <small>配对码（已使用，不能再次配对）</small>
                        <CopyCode
                          key={device.pairingCode}
                          code={device.pairingCode}
                          label={`${device.label}的已用配对码`}
                        />
                      </>
                    ) : (
                      <p>配对码：历史记录未保存</p>
                    )}
                    <details>
                      <summary>修改设备型号</summary>
                      <label>
                        设备型号
                        <input
                          value={deviceModels[device.id] ?? device.model ?? ''}
                          maxLength={80}
                          placeholder="例如：iPad Air 5"
                          onChange={(event) =>
                            setDeviceModels((current) => ({
                              ...current,
                              [device.id]: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <button
                        className="quiet"
                        disabled={busy || !(deviceModels[device.id] ?? device.model ?? '').trim()}
                        onClick={() =>
                          void act(async () => {
                            await api(`/devices/${device.id}`, {
                              method: 'PUT',
                              body: JSON.stringify({
                                model: deviceModels[device.id] ?? device.model,
                              }),
                            });
                            await reloadDevices();
                          })
                        }
                      >
                        保存设备型号
                      </button>
                    </details>
                  </div>
                  {!device.current &&
                    (revokeDeviceId === device.id ? (
                      <div className="device-actions">
                        <button
                          className="danger-button"
                          onClick={() =>
                            void act(async () => {
                              await api(`/devices/${device.id}`, { method: 'DELETE' });
                              setRevokeDeviceId('');
                              await reloadDevices();
                              await refresh();
                            })
                          }
                        >
                          确认撤销
                        </button>
                        <button className="quiet" onClick={() => setRevokeDeviceId('')}>
                          取消
                        </button>
                      </div>
                    ) : (
                      <button className="quiet" onClick={() => setRevokeDeviceId(device.id)}>
                        撤销设备
                      </button>
                    ))}
                </li>
              ))}
            </ul>
            {devices.length === 0 && <p>目前没有已配对设备。</p>}
            <Notice
              error={deviceError}
              onReconnect={() =>
                void act(async () => {
                  await reloadDevices();
                  setDeviceError('');
                })
              }
            />
          </div>
        )}
      </details>
      <details className="parent-section">
        <summary>备份与恢复</summary>
        <Notice
          error={/^(BACKUP_|IMPORT_)/.test(error) ? error : ''}
          onReconnect={() => void act(refresh)}
        />
        <div className="parent-setting">
          <div>
            <strong>学习进度</strong>
            <p>
              家庭进度修订号 {progress.revision} · {progress.attemptCount ?? 0} 次练习记录
            </p>
          </div>
          <button
            className="quiet"
            disabled={!boot.device?.isParent}
            onClick={() =>
              void act(async () => {
                const data = await api('/profiles/export');
                const contents = JSON.stringify(data, null, 2);
                setExportJson(contents);
                const downloadUrl = URL.createObjectURL(
                  new Blob([contents], { type: 'application/json' }),
                );
                const downloadLink = document.createElement('a');
                downloadLink.href = downloadUrl;
                downloadLink.download = `love-pinyin-backup-${new Date().toISOString().slice(0, 10)}.json`;
                document.body.append(downloadLink);
                downloadLink.click();
                downloadLink.remove();
                window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
                setExportRevision(data.profile.revision);
              })
            }
          >
            导出家庭数据
          </button>
        </div>
        {exportJson && exportRevision === progress.revision && (
          <div>
            <p role="status">已生成家庭备份并开始下载，请在浏览器下载中确认文件已保存。</p>
            <details>
              <summary>技术详情：查看 JSON</summary>
              <textarea
                className="export-box"
                aria-label="导出的 JSON 数据"
                readOnly
                value={exportJson}
              />
            </details>
          </div>
        )}
        <div className="parent-setting import-setting">
          <div>
            <strong>从家庭备份恢复</strong>
            <p>备份只发送到此 Mac Studio 的家庭网络服务，不会发送给第三方。</p>
          </div>
          <label className="file-control">
            选择 JSON 备份
            <input
              aria-label="导入家庭备份文件"
              type="file"
              accept="application/json,.json"
              disabled={!isParent}
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.currentTarget.value = '';
                setImportPreview(null);
                setImportConfirmation('');
                setImportComplete(false);
                if (!file) return;
                void act(async () => {
                  if (file.size > 1_048_576) throw new Error('BACKUP_TOO_LARGE');
                  const contents = await file.text();
                  const result = await api('/profiles/import-preview', {
                    method: 'POST',
                    body: contents,
                  });
                  setImportFileName(file.name);
                  setImportPreview(result);
                });
              }}
            />
          </label>
          {importPreview && (
            <div className="import-preview" aria-label="备份导入预览">
              <strong>{importFileName} · 已通过格式检查</strong>
              {importPreview.migratedFromContentVersion && (
                <p>这份备份来自较早课程，恢复后会保留当时的题目和成绩。</p>
              )}
              {importPreview.migratedFromSchemaVersion && (
                <p>
                  这份 schema v{importPreview.migratedFromSchemaVersion}{' '}
                  备份已显式迁移；旧备份没有待校时标记，历史练习按普通记录导入。
                </p>
              )}
              <p>
                将整体替换为 {importPreview.counts.attempts} 条练习、
                {importPreview.counts.sessions} 个会话、
                {importPreview.counts.skippedInstances} 道跳过题和
                {importPreview.counts.reviewPlans} 项复习计划；其中待校时练习{' '}
                {importPreview.counts.clockPendingAttempts ?? 0} 条。
              </p>
              <p>此操作会替换本家庭全部学习记录；已经下载的旧备份无法远程删除。</p>
              <label className="import-confirm-label">
                输入“替换家庭学习档案”确认
                <input
                  aria-label="确认替换家庭学习档案文字"
                  value={importConfirmation}
                  onChange={(event) => setImportConfirmation(event.target.value)}
                />
              </label>
              <button
                className="danger-button"
                disabled={!isParent || importConfirmation !== '替换家庭学习档案' || busy}
                onClick={() =>
                  void act(async () => {
                    await api('/profiles/import', {
                      method: 'POST',
                      body: JSON.stringify({
                        previewToken: importPreview.previewToken,
                        sha256: importPreview.sha256,
                        expectedRevision: importPreview.revision,
                      }),
                    });
                    setImportPreview(null);
                    setImportConfirmation('');
                    setImportComplete(true);
                    setExportJson('');
                    setExportRevision(null);
                    await refresh();
                  })
                }
              >
                确认替换家庭数据
              </button>
            </div>
          )}
          {importComplete && <p role="status">家庭数据已恢复。</p>}
        </div>
      </details>
      <details className="parent-section">
        <summary>删除与重置</summary>
        <div className="parent-setting danger-setting">
          <div>
            <strong>删除所有学习记录</strong>
            <p>删除后无法恢复。输入“删除我的学习记录”后才会启用。</p>
          </div>
          <input
            aria-label="确认删除文字"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            placeholder="输入确认文字"
          />
          <button
            className="danger-button"
            disabled={!boot.device?.isParent || confirm !== '删除我的学习记录'}
            onClick={() => {
              if (confirm === '删除我的学习记录')
                void act(async () => {
                  await api('/profiles/data', {
                    method: 'DELETE',
                    body: JSON.stringify({ confirmation: confirm }),
                  });
                  setExportJson('');
                  setExportRevision(null);
                  setConfirm('');
                  await refresh();
                });
            }}
          >
            删除记录
          </button>
        </div>
        <div className="parent-setting danger-setting">
          <div>
            <strong>重置家庭档案</strong>
            <p>
              将删除全家的学习记录和家长设置，并撤销所有浏览器配对、清除未使用的配对码。完成后需在
              Mac 本机重新配对。课程与应用不会卸载；已下载的备份无法远程删除。
            </p>
          </div>
          <input
            aria-label="确认重置家庭档案文字"
            value={resetConfirm}
            onChange={(event) => setResetConfirm(event.target.value)}
            placeholder="输入重置家庭档案"
          />
          <button
            className="danger-button"
            disabled={!isParent || resetConfirm !== '重置家庭档案' || busy}
            onClick={() => {
              if (resetConfirm === '重置家庭档案')
                void act(async () => {
                  await api('/profiles/reset', {
                    method: 'DELETE',
                    body: JSON.stringify({ confirmation: resetConfirm }),
                  });
                  window.location.reload();
                });
            }}
          >
            重置家庭档案
          </button>
        </div>
      </details>
      <ReleaseHistory contentVersion={curriculum.contentVersion} />
      <button
        className="quiet"
        onClick={() =>
          void act(async () => {
            await api('/session', { method: 'DELETE' });
            window.location.reload();
          })
        }
      >
        退出此设备配对
      </button>
      {!boot.device?.isParent && <p className="adult-hint">此设备尚未取得家长管理权限。</p>}
    </section>
  );
}
