import { androidOperation, isAndroidApp } from './android-app';
type Bridge = { postMessage(message: object): Promise<unknown> };

function bridge() {
  if (typeof window === 'undefined') return undefined;
  const host = window as Window & {
    __lovePinyinIOS?: boolean;
    webkit?: { messageHandlers?: { learning?: Bridge } };
  };
  return host.__lovePinyinIOS === true ? host.webkit?.messageHandlers?.learning : undefined;
}

export function isNativeApp() {
  return isAndroidApp() || Boolean(bridge());
}

export async function nativeOperation<T>(operation: string, fields: Record<string, unknown> = {}) {
  if (isAndroidApp()) return androidOperation<T>(operation, fields);
  const handler = bridge();
  if (!handler) throw new Error('IOS_BRIDGE_UNAVAILABLE');
  return (await handler.postMessage({ version: 1, operation, ...fields })) as T;
}
