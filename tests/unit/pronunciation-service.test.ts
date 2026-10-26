import { describe, expect, it, vi } from 'vitest';
import type { PronunciationRequest, PronunciationTarget } from '../../src/domain/pronunciation';
import { createPronunciationService } from '../../src/platform/audio/pronunciation-service';

const targets: PronunciationTarget[] = [
  { id: 'test-a', pinyin: 'nǚ', task: 'syllable' },
  { id: 'test-b', pinyin: 'nǐ hǎo', task: 'sequence' },
];
const request = (targetId = 'test-a', audio = new Blob()): PronunciationRequest => ({
  requestId: `request-${targetId}`,
  targetId,
  audio,
});

describe('pronunciation v1 development port', () => {
  it('always matches registered targets even with empty or invalid audio, without reading it', async () => {
    const service = createPronunciationService({ mode: 'mock', targets });
    for (const audio of [new Blob(), new Blob(['not a WAV'])]) {
      const read = vi.spyOn(audio, 'arrayBuffer');
      expect(await service.match(request('test-a', audio))).toEqual({
        contractVersion: 1,
        requestId: 'request-test-a',
        targetId: 'test-a',
        evidence: 'mock',
        toneAssessed: false,
        status: 'matched',
        reason: null,
      });
      expect(read).not.toHaveBeenCalled();
    }
  });

  it('returns exactly the expected content and independent request identities concurrently', async () => {
    const service = createPronunciationService({ mode: 'mock', targets });
    const results = await Promise.all(
      targets.map((target) => service.recognize(request(target.id))),
    );
    expect(results.map((result) => result.recognizedPinyin)).toEqual(['nǚ', 'nǐ hǎo']);
    for (const [index, result] of results.entries()) {
      expect(result).toMatchObject({
        status: 'recognized',
        targetId: targets[index]!.id,
        requestId: `request-${targets[index]!.id}`,
        evidence: 'mock',
        toneAssessed: false,
        reason: null,
      });
    }
  });

  it('snapshots the injected catalog and normalizes display pinyin to NFC', async () => {
    const catalog: PronunciationTarget[] = [
      { id: 'one', pinyin: 'nu\u0308\u030c', task: 'syllable' },
    ];
    const service = createPronunciationService({ mode: 'mock', targets: catalog });
    catalog[0] = { id: 'one', pinyin: 'changed', task: 'syllable' };
    expect(await service.recognize(request('one'))).toMatchObject({ recognizedPinyin: 'nǚ' });
  });

  it('never falls back to mock when omitted or explicitly unavailable', async () => {
    for (const mode of [undefined, 'unavailable'] as const) {
      const service = createPronunciationService({ mode, targets });
      expect(await service.match(request())).toMatchObject({
        status: 'unavailable',
        evidence: 'none',
        reason: 'not-configured',
      });
      expect(await service.recognize(request())).toMatchObject({
        status: 'unavailable',
        recognizedPinyin: null,
        evidence: 'none',
      });
    }
  });

  it('does not invent results for unsupported targets', async () => {
    const service = createPronunciationService({ mode: 'mock', targets });
    expect(await service.match(request('unknown'))).toMatchObject({
      status: 'unavailable',
      reason: 'unsupported-target',
    });
    expect(await service.recognize(request('unknown'))).toMatchObject({
      status: 'unavailable',
      recognizedPinyin: null,
      reason: 'unsupported-target',
    });
  });

  it('honors cancellation before and immediately after invocation for both operations', async () => {
    const service = createPronunciationService({ mode: 'mock', targets });
    for (const operation of ['match', 'recognize'] as const) {
      for (const alreadyAborted of [true, false]) {
        const controller = new AbortController();
        if (alreadyAborted) controller.abort();
        const result = service[operation]({ ...request(), signal: controller.signal });
        controller.abort();
        await expect(result).rejects.toMatchObject({ name: 'AbortError' });
      }
    }
    expect(await service.match(request())).toMatchObject({ status: 'matched' });
  });

  it('rejects ambiguous catalogs and missing correlation IDs', async () => {
    expect(() => createPronunciationService({ targets: [targets[0]!, targets[0]!] })).toThrow(
      'INVALID_PRONUNCIATION_CATALOG',
    );
    expect(() =>
      createPronunciationService({ targets: [{ id: 'x', pinyin: '', task: 'final' }] }),
    ).toThrow();
    const service = createPronunciationService({ mode: 'mock', targets });
    await expect(service.match({ ...request(), requestId: '' })).rejects.toThrow(
      'INVALID_PRONUNCIATION_REQUEST',
    );
  });
});
