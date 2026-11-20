import { afterEach, describe, expect, it, vi } from 'vitest';
import { androidOperation, isAndroidApp } from '../../src/platform/android-app';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
describe('Android platform bridge', () => {
  it('requires native injection and an actual bridge', async () => {
    vi.stubGlobal('window', { __lovePinyinAndroid: true });
    expect(isAndroidApp()).toBe(false);
    await expect(androidOperation('classroom')).rejects.toThrow('ANDROID_BRIDGE_UNAVAILABLE');
  });
  it('correlates concurrent replies and propagates storage failures', async () => {
    const messages: { requestId: string; version: number; operation: string }[] = [];
    const host = {
      __lovePinyinAndroid: true,
      LovePinyinAndroid: { postMessage: (value: string) => messages.push(JSON.parse(value)) },
      __lovePinyinAndroidReply: undefined as undefined | ((value: object) => void),
    };
    vi.stubGlobal('window', host);
    const first = androidOperation('classroom');
    const second = androidOperation('practicePacks');
    expect(messages[0]?.version).toBe(1);
    host.__lovePinyinAndroidReply!({
      requestId: messages[1]!.requestId,
      result: { offline: true },
      error: null,
    });
    await expect(second).resolves.toEqual({ offline: true });
    host.__lovePinyinAndroidReply!({
      requestId: messages[0]!.requestId,
      result: null,
      error: 'ANDROID_STORAGE_FAILED',
    });
    await expect(first).rejects.toThrow('ANDROID_STORAGE_FAILED');
  });
});

it('keeps a slow native decode alive beyond the ordinary bridge timeout', async () => {
  vi.useFakeTimers();
  let requestId = '';
  const host = {
    __lovePinyinAndroid: true,
    LovePinyinAndroid: {
      postMessage: (value: string) => {
        requestId = JSON.parse(value).requestId;
      },
    },
    __lovePinyinAndroidReply: undefined as undefined | ((value: object) => void),
  };
  vi.stubGlobal('window', host);
  const request = androidOperation('recognizeAudio');
  await vi.advanceTimersByTimeAsync(31_000);
  host.__lovePinyinAndroidReply!({
    requestId,
    result: { status: 'recognized', pinyin: 'chá' },
    error: null,
  });
  await expect(request).resolves.toEqual({ status: 'recognized', pinyin: 'chá' });
});
