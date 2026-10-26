import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockShopCapture } from '../../src/platform/audio/mock-shop-capture';
import { createPronunciationService } from '../../src/platform/audio/pronunciation-service';
import { ShopReadingSession } from '../../src/platform/audio/shop-reading-session';
import { shopPcmWav, type ShopCapture } from '../../src/platform/audio/browser-shop-recorder';
import type {
  PronunciationMatchResult,
  PronunciationRequest,
  PronunciationService,
} from '../../src/domain/pronunciation';
const timing = { recognitionTimeoutMs: 5000, minimumAudioMs: 650, pollIntervalMs: 450 };
const target = { id: 'a', pinyin: 'a', task: 'final' as const };
const result = (
  r: PronunciationRequest,
  status: 'matched' | 'retry' | 'uncertain' = 'matched',
): PronunciationMatchResult =>
  status === 'uncertain'
    ? {
        contractVersion: 1,
        requestId: r.requestId,
        targetId: r.targetId,
        evidence: 'acoustic',
        toneAssessed: false,
        status,
        reason: 'insufficient-evidence',
      }
    : {
        contractVersion: 1,
        requestId: r.requestId,
        targetId: r.targetId,
        evidence: 'acoustic',
        toneAssessed: false,
        status,
        reason: null,
      };
function setup(match: PronunciationService['match']) {
  const capture: ShopCapture = {
    start: vi.fn(async () => undefined),
    snapshot: vi.fn(() => shopPcmWav(new Float32Array(16000), 16000)),
    discard: vi.fn(),
  };
  const session = new ShopReadingSession(capture, { match, recognize: vi.fn() }, false, timing);
  const callbacks = { phase: vi.fn(), outcome: vi.fn() };
  return { capture, session, callbacks };
}
beforeEach(() => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] }));
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
describe('SHOP-05: serial live snapshots within one five-second budget', () => {
  it('captures automatically and stops immediately when matched', async () => {
    const match = vi.fn(async (r: PronunciationRequest) => result(r));
    const { session, capture, callbacks } = setup(match);
    await session.start(target, callbacks);
    expect(callbacks.phase).toHaveBeenLastCalledWith('listening');
    await vi.advanceTimersByTimeAsync(650);
    expect(callbacks.outcome).toHaveBeenCalledExactlyOnceWith('matched');
    expect(capture.discard).toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(6000);
    expect(match).toHaveBeenCalledTimes(1);
  });
  it('continues uncertain snapshots serially and can match before the deadline', async () => {
    let count = 0;
    let concurrent = 0;
    let peak = 0;
    const match = vi.fn(async (r: PronunciationRequest) => {
      concurrent++;
      peak = Math.max(peak, concurrent);
      await new Promise((resolve) => setTimeout(resolve, 100));
      concurrent--;
      return result(r, ++count === 3 ? 'matched' : 'uncertain');
    });
    const { session, callbacks } = setup(match);
    await session.start(target, callbacks);
    await vi.advanceTimersByTimeAsync(2200);
    expect(match).toHaveBeenCalledTimes(3);
    expect(peak).toBe(1);
    expect(callbacks.outcome).toHaveBeenLastCalledWith('matched');
  });
  it('aborts an unresolved service at exactly five seconds and ignores its late success', async () => {
    let resolve!: (r: PronunciationMatchResult) => void;
    let request!: PronunciationRequest;
    const { session, callbacks } = setup((r) => {
      request = r;
      return new Promise((done) => {
        resolve = done;
      });
    });
    await session.start(target, callbacks);
    await vi.advanceTimersByTimeAsync(4999);
    expect(callbacks.outcome).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(callbacks.outcome).toHaveBeenCalledExactlyOnceWith('timeout');
    expect(request.signal?.aborted).toBe(true);
    resolve(result(request));
    await Promise.resolve();
    expect(callbacks.outcome).toHaveBeenCalledTimes(1);
  });
  it('clears pending microphone permission and old responses on selection cancellation', async () => {
    const { session, capture, callbacks } = setup(async (r) => result(r));
    let opened!: () => void;
    vi.mocked(capture.start).mockImplementation(
      () =>
        new Promise((done) => {
          opened = done;
        }),
    );
    const starting = session.start(target, callbacks);
    session.cancel();
    opened();
    await starting;
    await vi.advanceTimersByTimeAsync(6000);
    expect(callbacks.outcome).not.toHaveBeenCalled();
    expect(callbacks.phase).not.toHaveBeenCalledWith('listening');
  });
  it('rejects wrong correlation and gives retry only for actual evidence', async () => {
    const stale = setup(async (r) => ({ ...result(r), targetId: 'old' }));
    await stale.session.start(target, stale.callbacks);
    await vi.advanceTimersByTimeAsync(650);
    expect(stale.callbacks.outcome).toHaveBeenCalledWith('unavailable');
    const retry = setup(async (r) => result(r, 'retry'));
    await retry.session.start(target, retry.callbacks);
    await vi.advanceTimersByTimeAsync(650);
    expect(retry.callbacks.outcome).toHaveBeenCalledWith('retry');
  });
  it('reports microphone denial without invoking the matcher', async () => {
    const match = vi.fn(async (r: PronunciationRequest) => result(r));
    const { session, capture, callbacks } = setup(match);
    vi.mocked(capture.start).mockRejectedValue(new Error('denied'));
    await session.start(target, callbacks);
    expect(callbacks.outcome).toHaveBeenCalledWith('microphone');
    expect(match).not.toHaveBeenCalled();
  });
});
it('SHOP-05: PCM snapshots have the required rate, channels, signed samples and duration', async () => {
  const wav = shopPcmWav(new Float32Array(48000).fill(0.5), 48000);
  const data = new DataView(await wav.arrayBuffer());
  expect(wav.type).toBe('audio/wav');
  expect(data.getUint32(24, true)).toBe(16000);
  expect(data.getUint16(22, true)).toBe(1);
  expect(data.getUint16(34, true)).toBe(16);
  expect(data.getUint32(40, true)).toBe(32000);
  expect(data.getInt16(44, true)).toBe(16384);
});

it('SHOP-08: mock completes without a microphone or secure-context randomUUID', async () => {
  vi.stubGlobal('crypto', {});
  const capture = new MockShopCapture();
  const service = createPronunciationService({ mode: 'mock', targets: [target] });
  const session = new ShopReadingSession(capture, service, true, timing);
  const callbacks = { phase: vi.fn(), outcome: vi.fn() };
  await session.start(target, callbacks);
  await vi.advanceTimersByTimeAsync(650);
  expect(callbacks.outcome).toHaveBeenCalledExactlyOnceWith('matched');
});
