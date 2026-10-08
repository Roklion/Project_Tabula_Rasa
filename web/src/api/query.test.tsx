import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { api, ApiError } from './client';
import { session } from '../test/fixtures';
import { createPrivateCache, resourceKey, useCreateAccount } from './query';

it('qualifies cache by both server session scope and entity', () => {
  const cache = createPrivateCache();
  cache.setQueryData(resourceKey(session, 'accounts'), { private: 'alpha' });
  expect(cache.getQueryData(resourceKey({ ...session, entity: { id: 'beta', name: 'Beta' } }, 'accounts'))).toBeUndefined();
  expect(cache.getQueryData(resourceKey({ ...session, cache_scope: 'session-2' }, 'accounts'))).toBeUndefined();
  expect(cache.getDefaultOptions().mutations?.retry).toBe(false);
});

it('invalidates the affected scope after success and uncertain failure, with no automatic save retry', async () => {
  const cache = createPrivateCache();
  const alpha = resourceKey(session, 'accounts');
  const beta = resourceKey({ ...session, entity: { id: 'beta', name: 'Beta' } }, 'accounts');
  cache.setQueryData(alpha, { items: [] });
  cache.setQueryData(beta, { items: [] });
  const create = vi.spyOn(api, 'createAccount').mockRejectedValue(new ApiError('unavailable'));
  const { result } = renderHook(() => useCreateAccount(session), {
    wrapper: ({ children }) => <QueryClientProvider client={cache}>{children}</QueryClientProvider>,
  });
  act(() => result.current.mutate({ name: 'Bank', type: 'Bank', opening_balance: '0.00' }));
  await waitFor(() => expect(result.current.isError).toBe(true));
  expect(create).toHaveBeenCalledTimes(1);
  expect(cache.getQueryState(alpha)?.isInvalidated).toBe(true);
  expect(cache.getQueryState(beta)?.isInvalidated).toBe(false);
  create.mockResolvedValue({ id: 'a', name: 'Bank', type: 'Bank', classification: 'Asset',
    opening_balance: '0.00', active: true, parent_id: null, baseline: 'loaded', created_at: '2026-10-07T00:00:00Z' });
  cache.setQueryData(alpha, { items: [] });
  act(() => result.current.mutate({ name: 'Bank', type: 'Bank', opening_balance: '0.00' }));
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(create).toHaveBeenCalledTimes(2);
  expect(cache.getQueryState(alpha)?.isInvalidated).toBe(true);
});


it('retries an unavailable read exactly once and does not retry other failures', async () => {
  for (const [code, attempts] of [['unavailable', 2], ['forbidden', 1]] as const) {
    const cache = createPrivateCache();
    const queryFn = vi.fn().mockRejectedValue(new ApiError(code));
    await expect(cache.fetchQuery({ queryKey: ['probe', code], queryFn, retryDelay: 0 }))
      .rejects.toHaveProperty('code', code);
    expect(queryFn).toHaveBeenCalledTimes(attempts);
    cache.clear();
  }
});
