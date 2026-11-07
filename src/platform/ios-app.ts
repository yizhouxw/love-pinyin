type Bridge = { postMessage(message: object): Promise<unknown> };

function bridge() {
  if (typeof window === 'undefined') return undefined;
  const host = window as Window & {
    __lovePinyinIOS?: boolean;
    webkit?: { messageHandlers?: { learning?: Bridge } };
  };
  return host.__lovePinyinIOS === true ? host.webkit?.messageHandlers?.learning : undefined;
}

export function isIOSApp() {
  return Boolean(bridge());
}

export async function iosOperation<T>(operation: string, fields: Record<string, unknown> = {}) {
  const handler = bridge();
  if (!handler) throw new Error('IOS_BRIDGE_UNAVAILABLE');
  return (await handler.postMessage({ version: 1, operation, ...fields })) as T;
}
