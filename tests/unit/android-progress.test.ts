import { afterEach, expect, it, vi } from 'vitest';
import { readWordProgress, saveWordProgress } from '../../src/platform/word-practice-progress';
import { readDailyProgress, saveDailyProgress } from '../../src/platform/daily-progress';

afterEach(() => vi.unstubAllGlobals());
it('restores native practice marks and preserves earlier word marks when adding another', () => {
  const saved: Record<string, unknown> = { 'word:original': ['word-01:read'] };
  vi.stubGlobal('window', {
    __lovePinyinAndroid: true,
    LovePinyinAndroid: {
      postMessage: vi.fn(),
      practiceProgress: (key: string, payload: string) => {
        if (payload) saved[key] = JSON.parse(payload);
        return JSON.stringify({ result: saved[key] ?? null, error: null });
      },
    },
  });
  saveWordProgress(['word-02:write'], 'original');
  expect(readWordProgress('original')).toEqual(['word-01:read', 'word-02:write']);
  saveDailyProgress('original', { item1: 'practiced', item2: 'again' });
  expect(readDailyProgress('original')).toEqual({ item1: 'practiced', item2: 'again' });
});
it('does not overwrite native records after a failed read and reports failed writes', () => {
  const operation = vi.fn(() => JSON.stringify({ result: null, error: 'ANDROID_STORAGE_FAILED' }));
  vi.stubGlobal('window', {
    __lovePinyinAndroid: true,
    LovePinyinAndroid: { postMessage: vi.fn(), practiceProgress: operation },
  });
  expect(() => saveWordProgress(['new'], 'original')).toThrow('ANDROID_STORAGE_FAILED');
  expect(operation).toHaveBeenCalledTimes(1);
  expect(operation).toHaveBeenCalledWith('word:original', '');
  expect(() => saveDailyProgress('original', { item: 'practiced' })).toThrow(
    'ANDROID_STORAGE_FAILED',
  );
});
