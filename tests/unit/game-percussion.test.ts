import { afterEach, expect, it, vi } from 'vitest';
import { GamePercussion } from '../../src/platform/audio/game-percussion';
afterEach(() => vi.unstubAllGlobals());
it('closing a drum context during resume never leaks a rejected browser promise', async () => {
  let contexts = 0;
  class InterruptedContext {
    currentTime = 0;
    destination = {};
    constructor() {
      contexts++;
    }
    resume() {
      return Promise.reject(new Error('InvalidStateError: Context is closed'));
    }
    close() {
      return Promise.reject(new Error('already closed'));
    }
    createOscillator() {
      return {
        frequency: { setValueAtTime() {}, exponentialRampToValueAtTime() {} },
        connect() {},
        disconnect() {},
        start() {},
        stop() {},
        onended: null,
      };
    }
    createGain() {
      return {
        gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} },
        connect() {},
        disconnect() {},
      };
    }
  }
  vi.stubGlobal('AudioContext', InterruptedContext);
  const drum = new GamePercussion();
  drum.hit();
  drum.close();
  drum.hit();
  drum.close();
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(contexts).toBe(2);
});
