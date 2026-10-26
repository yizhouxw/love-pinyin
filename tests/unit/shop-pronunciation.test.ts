import { expect, it } from 'vitest';
import { shopPronunciation } from '../../src/platform/audio/shop-pronunciation';
const targets = [{ id: 'vowel', pinyin: 'ü', task: 'final' as const }];
const request = { requestId: 'request', targetId: 'vowel', audio: new Blob() };
it('SHOP-08: explicitly configured simulation matches in production without acoustic data', async () => {
  const adapter = shopPronunciation(targets);
  expect(adapter.mock).toBe(true);
  expect(adapter.configured).toBe(true);
  expect(await adapter.service.match(request)).toMatchObject({
    status: 'matched',
    evidence: 'mock',
    toneAssessed: false,
  });
});
it('SHOP-08: an unavailable service never silently falls back to simulation', async () => {
  const adapter = shopPronunciation(targets, 'unavailable');
  expect(adapter.mock).toBe(false);
  expect(adapter.configured).toBe(false);
  expect(await adapter.service.match(request)).toMatchObject({
    status: 'unavailable',
    evidence: 'none',
  });
});
