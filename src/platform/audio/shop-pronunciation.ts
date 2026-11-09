import { isIOSApp } from '../ios-app';
import { createIOSShopPronunciation, iosModelStatus } from './ios-recognition';
import { createHttpPronunciationService } from './pronunciation-http';

export function shopPronunciation(targets: readonly { id: string; pinyin: string }[] = []) {
  return isIOSApp() ? createIOSShopPronunciation(targets) : createHttpPronunciationService();
}

export async function shopRecognitionAvailable(signal: AbortSignal): Promise<boolean> {
  try {
    if (isIOSApp()) return (await iosModelStatus()).state === 'installed' && !signal.aborted;
    if (!navigator.mediaDevices?.getUserMedia || !crypto.randomUUID) return false;
    const response = await fetch('/api/v1/shop-recognition', { signal, cache: 'no-store' });
    return response.ok && (await response.json()).available === true;
  } catch {
    return false;
  }
}
