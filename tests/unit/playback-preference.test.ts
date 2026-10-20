import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  readPlaybackPreference,
  resolvePlaybackGap,
  savePlaybackPreference,
} from '../../src/platform/playback-preference';

function createStorage() {
  const values = new Map<string, string>();
  return {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => values.set(key, value)),
  };
}

beforeEach(() => {
  vi.stubGlobal('localStorage', createStorage());
  vi.stubGlobal('sessionStorage', createStorage());
});
afterEach(() => vi.unstubAllGlobals());

describe('device playback gap preference', () => {
  it('inherits the family default until a valid device choice is saved', () => {
    expect(readPlaybackPreference(false)).toBeNull();
    expect(resolvePlaybackGap(1, null)).toBe(1);
    savePlaybackPreference({ seconds: 0.3, familyDefault: 1 }, false);
    expect(resolvePlaybackGap(1, readPlaybackPreference(false))).toBe(0.3);
  });

  it('uses a changed family default instead of a choice based on the old default', () => {
    savePlaybackPreference({ seconds: 0.8, familyDefault: 1 }, false);
    expect(resolvePlaybackGap(2, readPlaybackPreference(false))).toBe(2);
    savePlaybackPreference({ seconds: 1.5, familyDefault: 2 }, false);
    expect(resolvePlaybackGap(2, readPlaybackPreference(false))).toBe(1.5);
  });

  it('keeps family and guest preferences in separate storage', () => {
    const family = { seconds: 0.1, familyDefault: 1 };
    const guest = { seconds: 5, familyDefault: 1 };
    savePlaybackPreference(family, false);
    savePlaybackPreference(guest, true);
    expect(localStorage.getItem('love-pinyin.playback-gap')).toBe(JSON.stringify(family));
    expect(sessionStorage.getItem('lp.guest.playback-gap')).toBe(JSON.stringify(guest));
    expect(localStorage.getItem('lp.guest.playback-gap')).toBeNull();
    expect(sessionStorage.getItem('love-pinyin.playback-gap')).toBeNull();
    expect(readPlaybackPreference(false)).toEqual(family);
    expect(readPlaybackPreference(true)).toEqual(guest);
  });

  it.each([
    'invalid json',
    'null',
    '[]',
    '3',
    '{}',
    '{"seconds":1}',
    '{"seconds":"1","familyDefault":1}',
    '{"seconds":0,"familyDefault":1}',
    '{"seconds":5.1,"familyDefault":1}',
    '{"seconds":1.05,"familyDefault":1}',
    '{"seconds":1,"familyDefault":0}',
    '{"seconds":1,"familyDefault":6}',
    '{"seconds":1,"familyDefault":0.15}',
  ])('ignores invalid persisted preference %s', (raw) => {
    localStorage.setItem('love-pinyin.playback-gap', raw);
    sessionStorage.setItem('lp.guest.playback-gap', raw);
    expect(readPlaybackPreference(false)).toBeNull();
    expect(readPlaybackPreference(true)).toBeNull();
  });

  it.each([NaN, Infinity, -Infinity, 0, 5.1, 0.15])(
    'does not persist an invalid gap of %s',
    (seconds) => {
      savePlaybackPreference({ seconds, familyDefault: 1 }, false);
      savePlaybackPreference({ seconds: 1, familyDefault: seconds }, true);
      expect(readPlaybackPreference(false)).toBeNull();
      expect(readPlaybackPreference(true)).toBeNull();
      expect(resolvePlaybackGap(1, { seconds, familyDefault: 1 })).toBe(1);
    },
  );

  it.each([false, true])('handles unavailable storage in guest mode %s', (guest) => {
    vi.stubGlobal(guest ? 'sessionStorage' : 'localStorage', {
      getItem() {
        throw new Error('Storage unavailable');
      },
      setItem() {
        throw new Error('Storage unavailable');
      },
    });
    expect(readPlaybackPreference(guest)).toBeNull();
    expect(() => savePlaybackPreference({ seconds: 0.5, familyDefault: 1 }, guest)).not.toThrow();
    expect(resolvePlaybackGap(1, { seconds: 0.5, familyDefault: 1 })).toBe(0.5);
  });
});
