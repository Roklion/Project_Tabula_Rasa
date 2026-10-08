import { describe, expect, it, vi } from 'vitest';
import { ApiError, createApi } from './client';

import { session } from '../test/fixtures';

describe('typed client', () => {
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
