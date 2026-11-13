import { isAndroidApp } from './android-app';

type ProgressHost = Window & {
  LovePinyinAndroid?: { practiceProgress(key: string, payload: string): string };
};
/** Small synchronous preference transactions; native returns only after SQLite commits. */
export function androidProgress<T>(key: string, value?: T): T | null {
  if (!isAndroidApp()) throw new Error('ANDROID_BRIDGE_UNAVAILABLE');
  const bridge = (window as ProgressHost).LovePinyinAndroid;
  if (!bridge?.practiceProgress) throw new Error('ANDROID_BRIDGE_UNAVAILABLE');
  const reply = JSON.parse(
    bridge.practiceProgress(key, value === undefined ? '' : JSON.stringify(value)),
  ) as { result: T | null; error: string | null };
  if (reply.error) throw new Error(reply.error);
  return reply.result;
}
