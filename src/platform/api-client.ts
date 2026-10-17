import type { Json } from '../domain/learning-api';
import { suggestedDeviceModel } from './device-info';
import { guestApi, isGuest } from './guest';

export async function api(path: string, options: RequestInit = {}): Promise<Json> {
  if (isGuest()) {
    try {
      return (await guestApi(path, options)) as Json;
    } catch (error) {
      if (error instanceof TypeError) throw new Error('MAC_UNREACHABLE', { cause: error });
      throw error;
    }
  }
  return householdApi(path, options);
}

export async function householdApi(path: string, options: RequestInit = {}): Promise<Json> {
  const headers = new Headers(options.headers);
  headers.set('X-LP-Device-Model', encodeURIComponent(suggestedDeviceModel()));
  if (options.body) headers.set('Content-Type', 'application/json');
  const csrf = document.cookie
    .split('; ')
    .find((item) => item.startsWith('lp_csrf='))
    ?.split('=')
    .slice(1)
    .join('=');
  if (csrf && options.method && options.method !== 'GET')
    headers.set('X-LP-CSRF', decodeURIComponent(csrf));
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      headers,
      credentials: 'same-origin',
    });
  } catch {
    throw new Error('MAC_UNREACHABLE');
  }
  if (response.status === 204) return {};
  const body: Json = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail as { code?: string } | undefined;
    throw new Error(detail?.code ?? `HTTP_${response.status}`);
  }
  return body;
}
