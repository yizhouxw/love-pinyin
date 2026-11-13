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
  const requestId = `android-${++sequence}`;
  return new Promise<T>((resolve, reject) => {
    pending.set(requestId, { resolve: (value) => resolve(value as T), reject });
    try {
      host.LovePinyinAndroid!.postMessage(
        JSON.stringify({ ...fields, version: 1, requestId, operation }),
      );
    } catch (error) {
      pending.delete(requestId);
      reject(error);
    }
  });
}
