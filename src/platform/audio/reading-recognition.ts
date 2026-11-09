import { recordingWav } from './recording-wav';
import { isGuest } from '../guest';
import { matchesDaily, observedSyllables, recognizeIOSAudio } from './ios-recognition';

export type RecognitionResult = {
  status: 'matched' | 'different' | 'uncertain' | 'unavailable';
  transcript?: string;
  recognizedPinyin?: string;
  reason?: string;
  mode: 'asr-syllable-match';
  toneAssessed: false;
};

/** Convert the current in-memory recording to bounded PCM; send only to the family Mac. */
export async function recognizeReading(
  itemId: string,
  url: string,
  signal: AbortSignal,
): Promise<RecognitionResult> {
  const wav = await recordingWav(url, signal);
  const headers = new Headers({ 'Content-Type': 'audio/wav' });
  const csrf = document.cookie
    .split('; ')
    .find((value) => value.startsWith('lp_csrf='))
    ?.slice('lp_csrf='.length);
  if (csrf && !isGuest()) headers.set('X-LP-CSRF', decodeURIComponent(csrf));
  const result = await fetch(
    `/api/v1/${isGuest() ? 'guest/' : ''}daily-reading/${encodeURIComponent(itemId)}/recognize`,
    {
      method: 'POST',
      body: wav,
      headers,
      signal,
      credentials: isGuest() ? 'omit' : 'same-origin',
    },
  );
  if (!result.ok) throw new Error(`RECOGNITION_HTTP_${result.status}`);
  return result.json() as Promise<RecognitionResult>;
}

export async function recognizeIOSReading(
  expected: readonly string[],
  audio: Blob,
  signal: AbortSignal,
): Promise<RecognitionResult> {
  const result = await recognizeIOSAudio(audio, false, signal);
  const context = { mode: 'asr-syllable-match', toneAssessed: false } as const;
  if (result.status !== 'recognized') return { ...context, status: result.status };
  const observed = observedSyllables(result.pinyin);
  const matched = matchesDaily(expected, observed);
  return {
    ...context,
    status: matched
      ? 'matched'
      : observed.length && /\p{Script=Han}/u.test(result.transcript)
        ? 'different'
        : 'uncertain',
    transcript: result.transcript,
    recognizedPinyin: observed.join(' '),
  };
}
