import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { SessionSummary } from '../../src/app/session-summary';
import type { useLearningVoice } from '../../src/app/learning-voice';

it('keeps uncertain clock records separate from independent, hinted, skipped and first-wrong outcomes', () => {
  const voice: ReturnType<typeof useLearningVoice> = {
    playingId: null,
    failureId: null,
    failedIds: new Set<string>(),
    completedIds: new Set<string>(),
    play: () => {},
    playStandard: () => {},
    playDaily: () => {},
    playSequence: () => {},
    retry: () => {},
    stop: () => {},
  };
  const html = renderToStaticMarkup(
    createElement(SessionSummary, {
      voice,
      busy: false,
      error: '',
      onFinish: () => {},
      onReconnect: () => {},
      session: {
        id: 'summary',
        gameId: 'shape',
        tasks: [],
        results: {
          independent: { correct: true, firstTryCorrect: true },
          hinted: { correct: true, firstTryCorrect: false, hintUsed: true },
          firstWrong: { correct: false, firstTryCorrect: false },
          skipped: { skipped: true },
          pendingCorrect: { correct: true, firstTryCorrect: true, clockPending: true },
          pendingWrong: { correct: false, firstTryCorrect: false, clockPending: true },
        },
      },
    }),
  )
    .replace(/<[^>]+>/g, '')
    .replace(/\s+/g, ' ');
  expect(html).toContain('独立答对：1 题');
  expect(html).toContain('提示后答对：1 题');
  expect(html).toContain('首次待巩固：1 题');
  expect(html).toContain('跳过：1 题');
  expect(html).toContain('待校时，不计成绩：2 题');
});
