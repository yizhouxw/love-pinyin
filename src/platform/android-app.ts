type AndroidHost = Window & {
  __lovePinyinAndroid?: boolean;
  LovePinyinAndroid?: { postMessage(value: string): void };
  __lovePinyinAndroidReply?: (value: {
    requestId: string;
    result: unknown;
    error: string | null;
  }) => void;
};
const pending = new Map<string, { resolve(value: unknown): void; reject(error: Error): void }>();
let sequence = 0;
const pageId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
export function isAndroidApp() {
  return (
    typeof window !== 'undefined' &&
    (window as AndroidHost).__lovePinyinAndroid === true &&
    Boolean((window as AndroidHost).LovePinyinAndroid)
  );
}
export function androidOperation<T>(
  operation: string,
  fields: Record<string, unknown> = {},
): Promise<T> {
  if (!isAndroidApp()) return Promise.reject(new Error('ANDROID_BRIDGE_UNAVAILABLE'));
  const host = window as AndroidHost;
  host.__lovePinyinAndroidReply ??= ({ requestId, result, error }) => {
    const request = pending.get(requestId);
    if (!request) return;
    pending.delete(requestId);
    if (error) request.reject(new Error(error));
    else request.resolve(result);
  };
  const requestId = `${pageId}-${++sequence}`;
  return new Promise<T>((resolve, reject) => {
    const timer = operation.startsWith('backup')
      ? undefined
      : setTimeout(() => {
          pending.delete(requestId);
          reject(new Error('ANDROID_BRIDGE_TIMEOUT'));
        }, 30000);
    pending.set(requestId, {
      resolve: (value) => {
        clearTimeout(timer);
        resolve(value as T);
      },
      reject: (error) => {
        clearTimeout(timer);
        reject(error);
      },
    });
    try {
      host.LovePinyinAndroid!.postMessage(
        JSON.stringify({ ...fields, version: 1, requestId, operation }),
      );
    } catch (error) {
      clearTimeout(timer);
      pending.delete(requestId);
      reject(error);
    }
  });
}
