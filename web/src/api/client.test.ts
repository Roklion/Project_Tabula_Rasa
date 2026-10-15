import { describe, expect, it, vi } from 'vitest';
import { ApiError, createApi } from './client';

import { session } from '../test/fixtures';

describe('typed client', () => {
  it('rechecks authority after a membership command loses access and does not retry', async () => {
    const notify = vi.spyOn(window, 'dispatchEvent');
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ error: { code: 'forbidden', message: 'safe' }, request_id: 'reference' }), { status: 403 }));
    const client = createApi(fetcher as typeof fetch);
    await expect(client.changeMember(session, 'member', { role: 'read_only', active: false, authorization_version: 1 }))
      .rejects.toMatchObject({ code: 'forbidden', requestId: 'reference' });
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ type: 'tabula:identity-check' }));
    expect(fetcher).toHaveBeenCalledTimes(1);
    notify.mockRestore();
    const successful = createApi(vi.fn(async () => new Response(null, { status: 204 })) as typeof fetch);
    await expect(successful.revokeInvitation(session, 'invitation')).resolves.toBeUndefined();
  });
  it('bootstraps only logout CSRF on reload and still reports unconfirmed revocation', async () => {
    const requests: Request[] = [];
    const client = createApi((async (request: Request) => {
      requests.push(request);
      return request.method === 'GET'
        ? new Response(JSON.stringify({ csrf_token: 'logout-only' }), { status: 200 })
        : new Response(JSON.stringify({ error: { code: 'unavailable' } }), { status: 503 });
    }) as typeof fetch);
    await expect(client.logout()).rejects.toMatchObject({ code: 'unavailable' });
    expect(requests).toHaveLength(2);
    expect(requests[0].url).toContain('/api/v1/auth/logout-context');
    expect(requests[0].headers.get('X-Tabula-Logout')).toBe('1');
    expect(requests[0].credentials).toBe('same-origin');
    expect(requests[1].headers.get('X-CSRF-Token')).toBe('logout-only');
  });

  it('does not send logout when its CSRF bootstrap fails', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ error: { code: 'forbidden' } }), { status: 403 }));
    await expect(createApi(fetcher as typeof fetch).logout()).rejects.toMatchObject({ code: 'forbidden' });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('uses same-origin scoped routes, credentials and CSRF without retrying a failed save', async () => {
    const requests: Request[] = [];
    const fetcher = vi.fn(async (request: Request) => {
      requests.push(request);
      return new Response(JSON.stringify({ error: { code: 'stale', message: 'safe' }, request_id: 'reference' }), { status: 409 });
    });
    const client = createApi(fetcher as typeof fetch);
    await expect(client.createAccount(session, { name: 'Draft', type: 'Bank', opening_balance: '1.25' }))
      .rejects.toMatchObject({ code: 'stale', requestId: 'reference' });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(requests[0].url).toContain('/api/v1/entities/alpha/accounts');
    expect(requests[0].credentials).toBe('same-origin');
    expect(requests[0].headers.get('X-CSRF-Token')).toBe('server-csrf');
    expect(requests[0].headers.get('X-Correlation-ID')).toBeTruthy();
  });

  it('hides raw network failures and preserves cancellation', async () => {
    const client = createApi(vi.fn().mockRejectedValue(new Error('private URL password')));
    await expect(client.session()).rejects.toEqual(new ApiError('unavailable'));
    const aborted = createApi(vi.fn().mockRejectedValue(new DOMException('Aborted', 'AbortError')));
    await expect(aborted.session()).rejects.toHaveProperty('name', 'AbortError');
  });

  it('passes a cancellation signal through to reads', async () => {
    let signal: AbortSignal | undefined;
    const client = createApi((async (request: Request) => {
      signal = request.signal;
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }) as typeof fetch);
    const controller = new AbortController();
    await client.accounts(session, controller.signal);
    controller.abort();
    expect(signal?.aborted).toBe(true);
  });
});


it('maps proxy JSON and HTML errors to a safe API error without leaking a TypeError', async () => {
  for (const body of [JSON.stringify({ message: 'private upstream detail' }), '<html>private upstream detail</html>']) {
    const fetcher = vi.fn(async () => new Response(body, { status: 502 }));
    const client = createApi(fetcher as typeof fetch);
    await expect(client.accounts(session)).rejects.toEqual(new ApiError('unavailable'));
    await expect(client.createAccount(session, { name: 'Draft', type: 'Bank', opening_balance: '0.00' }))
      .rejects.toEqual(new ApiError('unavailable'));
    expect(fetcher).toHaveBeenCalledTimes(2);
  }
});


it('sends large CSV selections in a body with CSRF and cancellation', async () => {
  let request: Request | undefined;
  const client = createApi(async input => {
    request = input as Request;
    return new Response('ID\nselected\n', { headers: { 'Content-Type': 'text/csv' } });
  });
  const ids = Array.from({ length: 400 }, (_, index) => `entry-${index}-${'x'.repeat(32)}`);
  const controller = new AbortController();
  await client.downloadSelectedLedgerCsv(session, ids, { kind: 'Expense' }, controller.signal);
  expect(request?.method).toBe('POST');
  expect(request?.url).not.toContain('?');
  expect(request?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
  expect(await request?.json()).toEqual({ entry_ids: ids, kind: 'Expense', account_ids: [], category_ids: [], tag_ids: [] });
});
