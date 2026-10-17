import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, householdApi } from '../../src/platform/api-client';
import { guestApi, isGuest } from '../../src/platform/guest';

vi.mock('../../src/platform/guest', () => ({ guestApi: vi.fn(), isGuest: vi.fn() }));
vi.mock('../../src/platform/device-info', () => ({ suggestedDeviceModel: () => '测试设备' }));

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(isGuest).mockReturnValue(false);
  vi.stubGlobal('document', { cookie: 'other=x; lp_csrf=token%3Dvalue' });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ revision: 3 })));
});
afterEach(() => vi.unstubAllGlobals());

describe('same-origin API transport', () => {
  it('preserves caller headers and attaches device metadata, credentials and write CSRF', async () => {
    await api('/household/settings', {
      method: 'PUT',
      headers: { 'X-Test': 'preserved' },
      body: JSON.stringify({ soundEnabled: false }),
    });
    const [url, options] = vi.mocked(fetch).mock.calls[0]!;
    expect(url).toBe('/api/v1/household/settings');
    expect(options?.credentials).toBe('same-origin');
    const headers = new Headers(options?.headers);
    expect(headers.get('X-Test')).toBe('preserved');
    expect(headers.get('X-LP-CSRF')).toBe('token=value');
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(decodeURIComponent(headers.get('X-LP-Device-Model')!)).toBe('测试设备');
  });

  it('reads without write headers and accepts empty successful responses', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }));
    expect(await householdApi('/session', { method: 'GET' })).toEqual({});
    const headers = new Headers(vi.mocked(fetch).mock.calls[0]![1]?.headers);
    expect(headers.has('X-LP-CSRF')).toBe(false);
    expect(headers.has('Content-Type')).toBe(false);
  });

  it('retains server error codes and reports non-JSON server failures', async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ detail: { code: 'REVISION_CONFLICT' } }, { status: 409 }),
    );
    await expect(api('/household/settings')).rejects.toThrow('REVISION_CONFLICT');
    vi.mocked(fetch).mockResolvedValue(new Response('gateway failed', { status: 502 }));
    await expect(api('/bootstrap')).rejects.toThrow('HTTP_502');
  });

  it('reports unconfirmed network operations as unreachable', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('offline'));
    await expect(api('/sessions', { method: 'POST' })).rejects.toThrow('MAC_UNREACHABLE');
  });

  it('uses guest transport for learning but household transport for pairing', async () => {
    vi.mocked(isGuest).mockReturnValue(true);
    vi.mocked(guestApi).mockResolvedValue({ revision: 8 });
    expect(await api('/profiles/progress')).toEqual({ revision: 8 });
    expect(fetch).not.toHaveBeenCalled();
    await householdApi('/bootstrap');
    expect(fetch).toHaveBeenCalledOnce();
    expect(guestApi).toHaveBeenCalledOnce();
  });

  it('normalizes guest network failures while preserving cache errors', async () => {
    vi.mocked(isGuest).mockReturnValue(true);
    vi.mocked(guestApi).mockRejectedValue(new TypeError('offline'));
    await expect(api('/sessions/current')).rejects.toThrow('MAC_UNREACHABLE');
    vi.mocked(guestApi).mockRejectedValue(new Error('GUEST_CACHE_FULL'));
    await expect(api('/sessions/current')).rejects.toThrow('GUEST_CACHE_FULL');
  });
});
