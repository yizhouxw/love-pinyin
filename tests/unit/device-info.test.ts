import { describe, expect, it } from 'vitest';
import { suggestedDeviceModel } from '../../src/platform/device-info';

describe('device display suggestions', () => {
  it('marks desktop-style iPad and ordinary desktop hints as guesses, without claiming a hardware model', () => {
    expect(
      suggestedDeviceModel({
        userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X)',
        maxTouchPoints: 5,
      }),
    ).toBe('iPad（浏览器推测，可修改具体型号）');
    expect(
      suggestedDeviceModel({
        userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X)',
        maxTouchPoints: 0,
      }),
    ).toBe('Mac（浏览器推测，可修改具体型号）');
    expect(suggestedDeviceModel({ userAgent: 'unknown', maxTouchPoints: 0 })).toBe('');
  });
});
