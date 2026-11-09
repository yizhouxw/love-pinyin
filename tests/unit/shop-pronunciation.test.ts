import { afterEach, expect, it, vi } from 'vitest';
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
