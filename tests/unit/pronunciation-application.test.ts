import { pronunciationTargets } from '../../src/platform/audio/pronunciation-development';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  coursePronunciationTargets,
  pronunciationSummary,
} from '../../src/domain/pronunciation-practice';
import { createHttpPronunciationService } from '../../src/platform/audio/pronunciation-http';

vi.mock('../../src/platform/guest', () => ({ isGuest: () => false }));
const context = {
  contractVersion: 1,
  requestId: 'request-test-1',
  targetId: 'rt-01-a1',
  evidence: 'acoustic',
  toneAssessed: false,
};
const assessment = () => ({
  match: { ...context, status: 'matched', reason: null },
  recognition: { ...context, status: 'recognized', recognizedPinyin: 'ā', reason: null },
  saved: true,
  createdAt: '2026-10-26T01:00:00+00:00',
});
const request = () => ({
  requestId: context.requestId,
  targetId: context.targetId,
  audio: new Blob(['test']),
  signal: new AbortController().signal,
});

afterEach(() => {
  vi.unstubAllGlobals();
});
describe('MATCH-13/14 application boundaries', () => {
  it('maps every centralized teaching form to a valid port task and keeps NFC ü', () => {
    expect(new Set(pronunciationTargets.map((item) => item.id)).size).toBe(
      pronunciationTargets.length,
    );
    expect(coursePronunciationTargets.length).toBe(79);
    expect(
      pronunciationTargets.every((item) =>
        ['initial', 'final', 'syllable', 'blend', 'sequence'].includes(item.task),
      ),
    ).toBe(true);
    expect(
      coursePronunciationTargets.some((item) => item.pinyin.includes('ǖ') && item.task === 'final'),
    ).toBe(true);
  });
  it('excludes refusal outcomes from the accuracy denominator', () => {
    expect(
      pronunciationSummary({
        items: [],
        counts: { matched: 2, retry: 1, uncertain: 7, unavailable: 3 },
      }),
    ).toEqual({ matched: 2, assessed: 3, undecided: 10 });
    expect(pronunciationSummary({ items: [], counts: {} }).assessed).toBe(0);
  });
  it('shares one bounded WAV request between MATCH-10 methods', async () => {
    vi.stubGlobal('document', { cookie: 'lp_csrf=csrf-value' });
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => assessment() });
    vi.stubGlobal('fetch', fetch);
    const service = createHttpPronunciationService();
    const input = request();
    const [match, recognition] = await Promise.all([
      service.match(input),
      service.recognize(input),
    ]);
    expect(match.status).toBe('matched');
    expect(recognition.status).toBe('recognized');
    expect(fetch).toHaveBeenCalledTimes(1);
    const options = fetch.mock.calls[0]![1];
    expect(options.body).toBe(input.audio);
    expect(options.headers.get('X-LP-CSRF')).toBe('csrf-value');
    expect(options.signal).toBe(input.signal);
  });
  it.each(['mock', 'wrong-request', 'wrong-target'])(
    'rejects untrusted %s responses',
    async (kind) => {
      vi.stubGlobal('document', { cookie: '' });
      const result = assessment();
      if (kind === 'mock') result.match.evidence = 'mock';
      if (kind === 'wrong-request') result.match.requestId = 'other';
      if (kind === 'wrong-target') result.recognition.targetId = 'other';
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => result }));
      expect(await createHttpPronunciationService().match(request())).toMatchObject({
        status: 'unavailable',
        evidence: 'none',
        reason: 'network-error',
      });
    },
  );
  it.each([
    [413, 'uncertain', 'invalid-audio'],
    [404, 'unavailable', 'unsupported-target'],
    [429, 'unavailable', 'busy'],
    [503, 'unavailable', 'model-unavailable'],
    [504, 'unavailable', 'timeout'],
  ])('handles HTTP %s without creating a wrong answer', async (code, status, reason) => {
    vi.stubGlobal('document', { cookie: '' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: code }));
    expect(await createHttpPronunciationService().match(request())).toMatchObject({
      status,
      reason,
      evidence: 'none',
    });
  });
  it('discards even a transport that returns after cancellation', async () => {
    vi.stubGlobal('document', { cookie: '' });
    const controller = new AbortController();
    controller.abort();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => assessment() }));
    await expect(
      createHttpPronunciationService().match({ ...request(), signal: controller.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' });
  });
});
