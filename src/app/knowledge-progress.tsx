import { useState } from 'react';
import type {
  AttemptHistoryPage,
  AttemptRecord,
  Curriculum,
  Knowledge,
  Lesson,
  Progress,
} from '../domain/learning-api';
import { api } from '../platform/api-client';
import { attemptOutcome, exerciseModeLabels, formatAttemptTime } from './labels';

export function KnowledgeProgress({
  curriculum,
  progress,
}: {
  curriculum: Curriculum;
  progress: Progress;
}) {
  const [attemptHistory, setAttemptHistory] = useState<Record<string, AttemptHistoryPage>>({});
  async function loadAttemptHistory(knowledgeId: string, cursor?: string) {
    if (attemptHistory[knowledgeId]?.loading) return;
    const previous = attemptHistory[knowledgeId];
    setAttemptHistory((current) => ({
      ...current,
      [knowledgeId]: {
        items: previous?.items ?? [],
        nextCursor: previous?.nextCursor ?? null,
        loaded: previous?.loaded ?? false,
        loading: true,
        error: false,
      },
    }));
    const params = new URLSearchParams({ limit: '8' });
    if (cursor) params.set('cursor', cursor);
    try {
      const page = await api(
        `/profiles/knowledge/${encodeURIComponent(knowledgeId)}/attempts?${params.toString()}`,
      );
      setAttemptHistory((current) => {
        const prior = current[knowledgeId];
        return {
          ...current,
          [knowledgeId]: {
            items: cursor
              ? [...(prior?.items ?? []), ...(page.items as AttemptRecord[])]
              : (page.items as AttemptRecord[]),
            nextCursor: typeof page.nextCursor === 'string' ? page.nextCursor : null,
            loaded: true,
            loading: false,
            error: false,
          },
        };
      });
    } catch {
      setAttemptHistory((current) => ({
        ...current,
        [knowledgeId]: {
          items: current[knowledgeId]?.items ?? [],
          nextCursor: current[knowledgeId]?.nextCursor ?? null,
          loaded: current[knowledgeId]?.loaded ?? false,
          loading: false,
          error: true,
        },
      }));
    }
  }

  return (
    <section className="parent-progress" aria-labelledby="parent-progress-title">
      <h3 id="parent-progress-title">按知识点查看进度</h3>
      <p className="parent-progress-note">
        状态由 Mac 根据最近练习记录计算；“独立答对”只统计首次作答且未用提示的客观题，不是考试成绩。
      </p>
      {curriculum.lessons.map((lesson: Lesson) => {
        const items = curriculum.knowledgeItems.filter(
          (item: Knowledge) => item.lessonId === lesson.id,
        );
        if (items.length === 0) return null;
        return (
          <details className="parent-lesson-progress" key={lesson.id}>
            <summary>
              {lesson.order}. {lesson.title}
            </summary>
            <ul>
              {items.map((item: Knowledge) => {
                const state = progress.mastery.find(
                  (entry: Progress['mastery'][number]) => entry.knowledgeId === item.id,
                );
                const statusLabel =
                  state?.status === 'mastered'
                    ? '已掌握'
                    : state?.status === 'practicing'
                      ? '练习中'
                      : '未开始';
                const requiredModes = (state?.requiredModes ?? [])
                  .map((mode: string) => exerciseModeLabels[mode])
                  .filter(Boolean);
                const coveredModes = (state?.coveredModes ?? [])
                  .filter((mode: string) => state?.requiredModes?.includes(mode))
                  .map((mode: string) => exerciseModeLabels[mode])
                  .filter(Boolean);
                const displayedAccuracy =
                  state?.sampleSize && state.accuracy !== null
                    ? Math.round(state.accuracy * 100)
                    : null;
                const history = attemptHistory[item.id];
                return (
                  <li key={item.id}>
                    <div className="parent-knowledge-title">
                      <strong>{item.symbol}</strong>
                      <span>{statusLabel}</span>
                      {state?.reviewDue && (
                        <span className="parent-due-label">
                          待复习{state.reviewDueDate ? ` · ${state.reviewDueDate}` : ''}
                        </span>
                      )}
                    </div>
                    <small>
                      {state && state.sampleSize > 0
                        ? `最近 ${state.sampleSize} 道有效练习：独立首次答对 ${state.correctCount} 题${displayedAccuracy === null ? '' : `（${displayedAccuracy}%）`}`
                        : `暂无有效练习记录${requiredModes.length ? ` · 需要练习：${requiredModes.join('、')}` : ''}`}
                    </small>
                    {state && state.sampleSize > 0 && (
                      <small>
                        独立答对覆盖：{coveredModes.length ? coveredModes.join('、') : '暂无'}；
                        本知识点要求：{requiredModes.length ? requiredModes.join('、') : '未配置'}
                      </small>
                    )}
                    <details
                      className="knowledge-attempt-history"
                      onToggle={(event) => {
                        if (event.currentTarget.open && !history?.loaded && !history?.loading)
                          void loadAttemptHistory(item.id);
                      }}
                    >
                      <summary>
                        查看练习记录
                        {history?.loaded ? `（已加载 ${history.items.length} 条）` : ''}
                      </summary>
                      {history?.loading && <p role="status">正在读取这项知识点的记录…</p>}
                      {history?.error && (
                        <div>
                          <p role="alert">暂时无法读取记录，请检查 Mac Studio 连接后重试。</p>
                          <button
                            className="quiet"
                            disabled={history.loading}
                            onClick={() =>
                              void loadAttemptHistory(item.id, history.nextCursor ?? undefined)
                            }
                          >
                            重试读取
                          </button>
                        </div>
                      )}
                      {history?.loaded && history.items.length === 0 && (
                        <p>这项知识点还没有练习记录。</p>
                      )}
                      {history && history.items.length > 0 && (
                        <ol>
                          {history.items.map((attempt: AttemptRecord) => (
                            <li key={attempt.id}>
                              <time dateTime={attempt.occurredAt}>
                                {formatAttemptTime(attempt.occurredAt)}
                              </time>
                              <span>{exerciseModeLabels[attempt.mode] ?? '其他练习'}</span>
                              <span>{attemptOutcome(attempt)}</span>
                            </li>
                          ))}
                        </ol>
                      )}
                      {history?.nextCursor && (
                        <button
                          className="quiet"
                          disabled={history.loading}
                          onClick={() =>
                            void loadAttemptHistory(item.id, history.nextCursor ?? undefined)
                          }
                        >
                          显示更早记录
                        </button>
                      )}
                    </details>
                  </li>
                );
              })}
            </ul>
          </details>
        );
      })}
    </section>
  );
}
