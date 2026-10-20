import playback from '../../content/playback.json';

export type PlaybackPreference = { seconds: number; familyDefault: number };

const FAMILY_KEY = 'love-pinyin.playback-gap';
const GUEST_KEY = 'lp.guest.playback-gap';

function validSeconds(value: unknown): value is number {
  if (
    typeof value !== 'number' ||
    !Number.isFinite(value) ||
    value < playback.gap.minSeconds ||
    value > playback.gap.maxSeconds
  )
    return false;
  const steps = value / playback.gap.stepSeconds;
  return Math.abs(steps - Math.round(steps)) < 1e-8;
}

function validPreference(value: unknown): value is PlaybackPreference {
  return (
    !!value &&
    typeof value === 'object' &&
    'seconds' in value &&
    'familyDefault' in value &&
    validSeconds(value.seconds) &&
    validSeconds(value.familyDefault)
  );
}

export function resolvePlaybackGap(
  defaultSeconds: number,
  preference: PlaybackPreference | null,
): number {
  return validPreference(preference) && preference.familyDefault === defaultSeconds
    ? preference.seconds
    : defaultSeconds;
}

export function readPlaybackPreference(guest: boolean): PlaybackPreference | null {
  try {
    const storage = guest ? sessionStorage : localStorage;
    const value: unknown = JSON.parse(storage.getItem(guest ? GUEST_KEY : FAMILY_KEY) ?? 'null');
    return validPreference(value) ? value : null;
  } catch {
    return null;
  }
}

export function savePlaybackPreference(value: PlaybackPreference, guest: boolean): void {
  if (!validPreference(value)) return;
  try {
    const storage = guest ? sessionStorage : localStorage;
    storage.setItem(guest ? GUEST_KEY : FAMILY_KEY, JSON.stringify(value));
  } catch {
    /* The current page remains usable without storage. */
  }
}
