import { isGuest } from '../guest';

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
  const buffer = await recordingWav(url, signal);
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
      body: buffer,
      headers,
      signal,
      credentials: isGuest() ? 'omit' : 'same-origin',
    },
  );
  if (!result.ok) throw new Error(`RECOGNITION_HTTP_${result.status}`);
  return result.json() as Promise<RecognitionResult>;
}

/** Shared bounded conversion for MATCH-10 and legacy daily ASR. */
export async function recordingWav(url: string, signal: AbortSignal): Promise<ArrayBuffer> {
  const response = await fetch(url, { signal });
  const context = new AudioContext();
  let decoded: AudioBuffer;
  try {
    decoded = await context.decodeAudioData(await response.arrayBuffer());
  } finally {
    await context.close();
  }
  if (signal.aborted) throw new DOMException('cancelled', 'AbortError');
  if (decoded.duration > 30) throw new Error('READING_TOO_LONG');
  const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * 16000), 16000);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start();
  const pcm = (await offline.startRendering()).getChannelData(0);
  if (signal.aborted) throw new DOMException('cancelled', 'AbortError');
  const buffer = new ArrayBuffer(44 + pcm.length * 2);
  const view = new DataView(buffer);
  const write = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };
  write(0, 'RIFF');
  view.setUint32(4, 36 + pcm.length * 2, true);
  write(8, 'WAVE');
  write(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true);
  view.setUint32(28, 32000, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, 'data');
  view.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) {
    const sample = Math.max(-1, Math.min(1, pcm[i]!));
    view.setInt16(44 + i * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
  }
  return buffer;
}
