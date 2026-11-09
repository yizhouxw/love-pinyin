import { isIOSApp } from '../ios-app';
import { createHttpPronunciationService } from './pronunciation-http';

export const shopPronunciation = createHttpPronunciationService;

export async function shopRecognitionAvailable(signal: AbortSignal): Promise<boolean> {
  if (isIOSApp() || !navigator.mediaDevices?.getUserMedia || !crypto.randomUUID) return false;
  try {
    const response = await fetch('/api/v1/shop-recognition', { signal, cache: 'no-store' });
    return response.ok && (await response.json()).available === true;
  } catch {
    return false;
  }
}
