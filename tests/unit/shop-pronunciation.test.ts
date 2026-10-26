import { afterEach, expect, it, vi } from 'vitest';
import { shopPronunciation } from '../../src/platform/audio/shop-pronunciation';
const targets = [{ id: 'vowel', pinyin: 'ü', task: 'final' as const }];
const request = { requestId: 'request', targetId: 'vowel', audio: new Blob() };
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});
it('SHOP-02: production query parameters cannot enable mock', async () => {
  vi.stubEnv('DEV', false);
  vi.stubGlobal('location', { search: '?shopRecognition=mock' });
  const adapter = shopPronunciation(targets);
  expect(adapter.mock).toBe(false);
  expect(adapter.configured).toBe(false);
  expect((await adapter.service.match(request)).status).toBe('unavailable');
});
it('SHOP-02: development must explicitly opt in to fixed-success simulation', async () => {
  vi.stubEnv('DEV', true);
  vi.stubGlobal('location', { search: '' });
  expect(shopPronunciation(targets).mock).toBe(false);
  vi.stubGlobal('location', { search: '?shopRecognition=mock' });
  const adapter = shopPronunciation(targets);
  expect(adapter.configured).toBe(true);
  expect(await adapter.service.match(request)).toMatchObject({
    status: 'matched',
    evidence: 'mock',
    toneAssessed: false,
  });
});
