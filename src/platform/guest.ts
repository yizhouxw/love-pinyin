/** Per-tab temporary progress. No cookies, localStorage or server guest account. */
const CACHE_KEY = 'lp.guest.v1';
let guestMode: boolean | undefined;
let leaving = false;

export function isGuest(): boolean {
  if (guestMode !== undefined) return guestMode;
  try {
    guestMode = sessionStorage.getItem(CACHE_KEY) !== null;
    return guestMode;
  } catch {
    return false;
  }
}

export function startGuest() {
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify({ state: null }));
    guestMode = true;
    leaving = false;
  } catch {
    throw new Error('浏览器临时缓存不可用，请允许网站存储后再体验');
  }
}

export function leaveGuest() {
  sessionStorage.removeItem(CACHE_KEY);
  leaving = true;
  for (const key of Object.keys(sessionStorage)) {
    if (key.startsWith('lp.guest.pending-answer.')) sessionStorage.removeItem(key);
  }
  window.location.reload();
}

export function learningAssetUrl(kind: 'audio' | 'voice' | 'daily-audio', id: string) {
  return `/api/v1/${isGuest() ? 'guest/' : ''}${kind}/${encodeURIComponent(id)}`;
}

async function readResponse(response: Response): Promise<Record<string, unknown>> {
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail?.code ?? `HTTP_${response.status}`);
  return body;
}

// Even reads return refreshed snapshots. Serialize concurrent React refreshes so
// an older snapshot can never overwrite an answer or a lesson change.
let queue: Promise<unknown> = Promise.resolve();
export function guestApi(path: string, options: RequestInit): Promise<unknown> {
  const work = queue.then(async () => {
    if (leaving) throw new Error('GUEST_EXITED');
    if (path === '/curriculum' || path === '/learning-audio') {
      return readResponse(await fetch(`/api/v1/guest${path}`, { credentials: 'omit' }));
    }
    let cached: { state: unknown };
    try {
      cached = JSON.parse(sessionStorage.getItem(CACHE_KEY) ?? 'null');
      if (!cached || !Object.hasOwn(cached, 'state')) throw new Error();
    } catch {
      throw new Error('GUEST_CACHE_INVALID');
    }
    const response = await fetch('/api/v1/guest/operate', {
      method: 'POST',
      credentials: 'omit',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path,
        method: options.method ?? 'GET',
        body: options.body ? JSON.parse(String(options.body)) : {},
        state: cached.state,
      }),
    });
    const payload = await readResponse(response);
    if (leaving) throw new Error('GUEST_EXITED');
    try {
      sessionStorage.setItem(CACHE_KEY, JSON.stringify({ state: payload.state }));
    } catch {
      throw new Error('GUEST_CACHE_FULL');
    }
    return payload.result;
  });
  queue = work.catch(() => undefined);
  return work;
}
