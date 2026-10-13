import { describe, expect, it } from 'vitest';
import { resolveGuidance } from '../src/platform/guidance-preference';

describe('shared guidance preference', () => {
  it('inherits the parent setting without a device choice', () => {
    expect(resolveGuidance(false, null)).toBe(false);
    expect(resolveGuidance(true, null)).toBe(true);
  });
  it('uses a device choice only for its matching family setting', () => {
    expect(resolveGuidance(true, { enabled: false, familyDefault: true })).toBe(false);
    expect(resolveGuidance(false, { enabled: true, familyDefault: true })).toBe(false);
    expect(resolveGuidance(true, { enabled: false, familyDefault: false })).toBe(true);
    expect(resolveGuidance(false, { enabled: true, familyDefault: false })).toBe(true);
  });
});
