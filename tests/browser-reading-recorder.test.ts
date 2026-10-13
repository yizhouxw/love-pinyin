import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BrowserReadingRecorder } from '../src/platform/audio/browser-reading-recorder';

class FakeRecorder {
  static instances: FakeRecorder[] = [];
  state = 'inactive';
  mimeType = 'audio/webm';
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  constructor() {
    FakeRecorder.instances.push(this);
  }
  start() {
    this.state = 'recording';
  }
  stop() {
    this.state = 'inactive';
  }
  finish() {
    this.ondataavailable?.({ data: new Blob(['synthetic-capture-lifecycle-only']) });
    this.onstop?.();
  }
}

describe('ephemeral browser capture lifetime', () => {
  const trackStop = vi.fn();
  const getUserMedia = vi.fn();
  beforeEach(() => {
    FakeRecorder.instances = [];
    trackStop.mockClear();
    getUserMedia.mockReset().mockResolvedValue({ getTracks: () => [{ stop: trackStop }] });
    vi.stubGlobal('window', { isSecureContext: true, MediaRecorder: FakeRecorder });
    vi.stubGlobal('MediaRecorder', FakeRecorder);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
    vi.stubGlobal('document', { hidden: false });
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:ephemeral');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  it('releases the microphone immediately and revokes completed capture on discard', async () => {
    const capture = new BrowserReadingRecorder();
    const ready = vi.fn();
    await capture.start(ready, vi.fn());
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true, video: false });
    capture.stop();
    expect(trackStop).toHaveBeenCalledTimes(1);
    FakeRecorder.instances[0]!.finish();
    expect(ready).toHaveBeenCalledWith('blob:ephemeral');
    capture.discard();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:ephemeral');
  });
  it('closes a permission request that resolves after leaving the item', async () => {
    let grant!: (value: unknown) => void;
    getUserMedia.mockReturnValue(
      new Promise((resolve) => {
        grant = resolve;
      }),
    );
    const capture = new BrowserReadingRecorder();
    const pending = capture.start(vi.fn(), vi.fn());
    const rejection = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    capture.discard();
    grant({ getTracks: () => [{ stop: trackStop }] });
    await rejection;
    expect(trackStop).toHaveBeenCalledTimes(1);
    expect(FakeRecorder.instances).toHaveLength(0);
  });
  it('ignores old stop events without stopping a newer recording', async () => {
    const capture = new BrowserReadingRecorder();
    const oldReady = vi.fn();
    await capture.start(oldReady, vi.fn());
    await capture.start(vi.fn(), vi.fn());
    const stopsBefore = trackStop.mock.calls.length;
    FakeRecorder.instances[0]!.finish();
    expect(trackStop).toHaveBeenCalledTimes(stopsBefore);
    expect(oldReady).not.toHaveBeenCalled();
    expect(FakeRecorder.instances[1]!.state).toBe('recording');
    capture.discard();
  });
  it('permission refusal creates no recording or result', async () => {
    const capture = new BrowserReadingRecorder();
    const ready = vi.fn();
    getUserMedia.mockRejectedValue(new DOMException('denied', 'NotAllowedError'));
    await expect(capture.start(ready, vi.fn())).rejects.toMatchObject({ name: 'NotAllowedError' });
    expect(ready).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
