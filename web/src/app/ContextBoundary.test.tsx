import { useContext, useState } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { resourceKey } from '../api/query';
import { session } from '../test/fixtures';
import { ContextBoundary } from './ContextBoundary';
import { EntitySelectionContext } from './entitySelectionContext';
import { useEntity } from './context';
import { AuthContext } from './authContext';

afterEach(() => vi.restoreAllMocks());

it('preserves the private scope after a failed switch and replaces it only after confirmation', async () => {
  const beta = { ...session, entity: { id: 'beta', name: 'Beta' } };
  vi.spyOn(api, 'session').mockResolvedValue(session);
  vi.spyOn(api, 'entities').mockResolvedValue({ items: [session.entity, beta.entity] });
  const select = vi.spyOn(api, 'selectEntity').mockRejectedValueOnce(new ApiError('unavailable')).mockResolvedValue(beta);
  const caches: QueryClient[] = [];
  function Feature() {
    const current = useEntity();
    const selection = useContext(EntitySelectionContext)!;
    const cache = useQueryClient();
    if (!caches.includes(cache)) caches.push(cache);
    const [draft, setDraft] = useState('');
    return <><p>Current business: {current.entity.name}</p>
      <input aria-label="Draft" value={draft} onChange={event => setDraft(event.target.value)} />
      <button onClick={() => void selection.select('beta')}>Select Beta</button></>;
  }
  render(<ContextBoundary><Feature /></ContextBoundary>);
  await screen.findByText('Current business: Alpha');
  const key = resourceKey(session, 'accounts');
  caches[0].setQueryData(key, { private: 'alpha ledger' });
  fireEvent.change(screen.getByLabelText('Draft'), { target: { value: 'Alpha private draft' } });
  fireEvent.click(screen.getByRole('button', { name: 'Select Beta' }));
  await screen.findByRole('alert');
  expect(screen.getByText('Current business: Alpha')).toBeVisible();
  expect(screen.getByLabelText('Draft')).toHaveValue('Alpha private draft');
  expect(caches).toHaveLength(1);
  expect(caches[0].getQueryData(key)).toEqual({ private: 'alpha ledger' });
  expect(select).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Select Beta' }));
  await screen.findByText('Current business: Beta');
  expect(screen.getByLabelText('Draft')).toHaveValue('');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(caches).toHaveLength(2);
  await waitFor(() => expect(caches[0].getQueryCache().getAll()).toHaveLength(0));
  expect(caches[1].getQueryCache().getAll()).toHaveLength(0);
  expect(select).toHaveBeenCalledTimes(2);
});

it('does not compose private UI for needs-setup or failed initial identity', async () => {
  const identity = { state: 'needs_setup' as const, actor_id: 'alice', organization_id: null,
    entity: null, capabilities: [], cache_scope: 'new', csrf_token: 'csrf', trusted_development: false as const };
  vi.spyOn(api, 'session').mockResolvedValue(identity);
  vi.spyOn(api, 'entities').mockResolvedValue({ items: [] });
  render(<ContextBoundary><p>Private ledger</p></ContextBoundary>);
  await screen.findByText('Workspace setup required');
  expect(screen.queryByText('Private ledger')).not.toBeInTheDocument();
});

it('clears private cache and drafts after authoritative session failure on focus', async () => {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  vi.spyOn(api, 'session').mockResolvedValueOnce({ ...session, trusted_development: false })
    .mockRejectedValue(new ApiError('unauthorized'));
  vi.spyOn(api, 'entities').mockResolvedValue({ items: [session.entity] });
  let cache: QueryClient | undefined;
  function Feature() {
    cache = useQueryClient();
    return <input aria-label="Private draft" defaultValue="Private receipt" />;
  }
  render(<ContextBoundary><Feature /></ContextBoundary>);
  await screen.findByLabelText('Private draft');
  cache!.setQueryData(['receipt'], 'Private cached receipt');
  fireEvent(window, new Event('focus'));
  await screen.findByRole('link', { name: 'Sign in' });
  expect(screen.queryByLabelText('Private draft')).not.toBeInTheDocument();
  await waitFor(() => expect(cache!.getQueryCache().getAll()).toHaveLength(0));
});

it('unmounts private UI even when server-side logout cannot be confirmed', async () => {
  vi.spyOn(api, 'session').mockResolvedValue({ ...session, trusted_development: false });
  vi.spyOn(api, 'entities').mockResolvedValue({ items: [session.entity] });
  vi.spyOn(api, 'logout').mockRejectedValue(new ApiError('unavailable'));
  function Feature() {
    const auth = useContext(AuthContext);
    return <><p>Private ledger</p><button onClick={auth.logout}>Sign out</button></>;
  }
  render(<ContextBoundary><Feature /></ContextBoundary>);
  fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }));
  await screen.findByRole('alert');
  expect(screen.queryByText('Private ledger')).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Sign in' })).toBeVisible();
});
