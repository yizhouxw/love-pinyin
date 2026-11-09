import { afterEach, expect, it, vi } from 'vitest';
import {
  baseSyllable,
  gameSyllable,
  matchesDaily,
  observedSyllables,
} from '../../src/platform/audio/ios-recognition';
import { shopPronunciation } from '../../src/platform/audio/shop-pronunciation';

vi.mock('../../src/platform/guest', () => ({ isGuest: () => true }));
afterEach(() => vi.unstubAllGlobals());

it('SHOP-09: a recognition failure cannot add an item', async () => {
  vi.stubGlobal('document', { cookie: '' });
  const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 503 }));
  vi.stubGlobal('fetch', fetcher);
  const audio = new Blob();
  const result = await shopPronunciation().match({
    requestId: 'request-id',
    targetId: 'v2-openmouth',
    audio,
  });
  expect(result).toMatchObject({ status: 'unavailable', evidence: 'none' });
  expect(fetcher).toHaveBeenCalledWith(
    '/api/v1/guest/pronunciation/v2-openmouth/assess',
    expect.objectContaining({ body: audio, method: 'POST' }),
  );
});

it('SHOP-14: iOS keeps ü and splits the native Mandarin transliteration into syllables', () => {
  expect(baseSyllable('lǜ')).toBe('lü');
  expect(observedSyllables('nǐ hǎo，lǜ。')).toEqual(['nǐ', 'hǎo', 'lǜ']);
  expect(observedSyllables('nǐ 404')).toEqual([]);
});

it('SHOP-15: iOS accepts game sound pairs without relaxing daily initial or final matching', () => {
  expect(gameSyllable('zhāng')).toBe(gameSyllable('zǎn'));
  expect(gameSyllable('shēng')).toBe(gameSyllable('sěn'));
  expect(gameSyllable('sěn')).not.toBe(gameSyllable('sān'));
  expect(matchesDaily(['zhāng'], ['zǎn'])).toBe(false);
  expect(matchesDaily(['nǐ', 'hǎo'], ['ní', 'hào'])).toBe(true);
  expect(matchesDaily(['nǐ', 'hǎo'], ['nǐ'])).toBe(false);
});
