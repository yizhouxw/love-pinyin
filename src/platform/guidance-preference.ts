export type GuidancePreference = { enabled: boolean; familyDefault: boolean };
const KEY = 'love-pinyin.guidance';

export function resolveGuidance(defaultEnabled: boolean, preference: GuidancePreference | null) {
  return preference?.familyDefault === defaultEnabled ? preference.enabled : defaultEnabled;
}

export function readGuidancePreference(): GuidancePreference | null {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(KEY) ?? 'null');
    if (
      value &&
      typeof value === 'object' &&
      'enabled' in value &&
      'familyDefault' in value &&
      typeof value.enabled === 'boolean' &&
      typeof value.familyDefault === 'boolean'
    )
      return value as GuidancePreference;
    // Preserve an explicit old opt-out; the old default opt-in must not override family settings.
    return localStorage.getItem('love-pinyin.daily-guidance') === 'off'
      ? { enabled: false, familyDefault: true }
      : null;
  } catch {
    return null;
  }
}

export function saveGuidancePreference(value: GuidancePreference) {
  try {
    localStorage.setItem(KEY, JSON.stringify(value));
    localStorage.removeItem('love-pinyin.daily-guidance');
  } catch {
    /* The current page remains usable without storage. */
  }
}
