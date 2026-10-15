import { useContext, useState } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { resourceKey } from '../api/query';
import { session } from '../test/fixtures';
import { ContextBoundary } from './ContextBoundary';
import { EntitySelectionContext } from './entitySelectionContext';
import { useEntity } from './context';
import { AuthContext } from './authContext';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function authChannel() {
  const channels: { onmessage?: (event: { data: string }) => void; close: ReturnType<typeof vi.fn> }[] = [];
  vi.stubGlobal('BroadcastChannel', class {
    onmessage?: (event: { data: string }) => void;
    close = vi.fn();
    postMessage = vi.fn();
    constructor(name: string) { expect(name).toBe('tabula-auth'); channels.push(this); }
  });
  return channels;
}

it.each(['resolve', 'reject'])('ignores a late initial session %s after cross-tab logout', async outcome => {
  const channels = authChannel();
  let resolve!: (value: typeof session) => void;
  let reject!: (error: unknown) => void;
  vi.spyOn(api, 'session').mockReturnValue(new Promise((done, fail) => { resolve = done; reject = fail; }));
  const entities = vi.spyOn(api, 'entities');
  const view = render(<ContextBoundary><p>Private ledger</p></ContextBoundary>);
  expect(channels).toHaveLength(1);
  act(() => channels[0].onmessage?.({ data: 'unrelated' }));
  expect(screen.queryByRole('link', { name: 'Sign in' })).not.toBeInTheDocument();
  act(() => channels[0].onmessage?.({ data: 'signed-out' }));
  expect(screen.getByRole('link', { name: 'Sign in' })).toBeVisible();
  await act(async () => {
    if (outcome === 'resolve') resolve({ ...session, trusted_development: false });
    else reject(new ApiError('unavailable'));
  });
  expect(screen.getByRole('link', { name: 'Sign in' })).toBeVisible();
  expect(screen.queryByText('Private ledger')).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(entities).not.toHaveBeenCalled();
  view.unmount();
  expect(channels[0].close).toHaveBeenCalledOnce();
});

it('clears an existing private scope on cross-tab logout', async () => {
  const channels = authChannel();
  vi.spyOn(api, 'session').mockResolvedValue({ ...session, trusted_development: false });
  vi.spyOn(api, 'entities').mockResolvedValue({ items: [session.entity] });
  let cache: QueryClient | undefined;
  function Feature() {
    cache = useQueryClient();
    return <input aria-label="Cross-tab draft" defaultValue="Private draft" />;
  }
  render(<ContextBoundary><Feature /></ContextBoundary>);
  await screen.findByLabelText('Cross-tab draft');
  cache!.setQueryData(['private'], 'Private ledger');
  act(() => channels[0].onmessage?.({ data: 'signed-out' }));
  expect(screen.getByRole('link', { name: 'Sign in' })).toBeVisible();
  expect(screen.queryByLabelText('Cross-tab draft')).not.toBeInTheDocument();
  await waitFor(() => expect(cache!.getQueryCache().getAll()).toHaveLength(0));
});

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

it('unmounts named private data while a switch is pending and after an uncertain response', async () => {
  const named = { ...session, trusted_development: false };
  vi.spyOn(api, 'session').mockResolvedValue(named);
  vi.spyOn(api, 'entities').mockResolvedValue({ items: [session.entity] });
  let reject!: (error: unknown) => void;
  vi.spyOn(api, 'selectEntity').mockReturnValue(new Promise((_, fail) => { reject = fail; }));
  let cache: QueryClient | undefined;
  function Feature() {
    const selection = useContext(EntitySelectionContext)!;
    cache = useQueryClient();
    return <><input aria-label="Named draft" defaultValue="Private alpha" />
      <button onClick={() => void selection.select('beta')}>Switch named business</button></>;
  }
  render(<ContextBoundary><Feature /></ContextBoundary>);
  await screen.findByLabelText('Named draft');
  cache!.setQueryData(['private'], 'Private alpha receipt');
  fireEvent.click(screen.getByRole('button', { name: 'Switch named business' }));
  expect(screen.queryByLabelText('Named draft')).not.toBeInTheDocument();
  await waitFor(() => expect(cache!.getQueryCache().getAll()).toHaveLength(0));
  await act(async () => reject(new ApiError('unavailable')));
  expect(screen.getByRole('alert')).toBeVisible();
  expect(screen.queryByLabelText('Named draft')).not.toBeInTheDocument();
});

it.each([true, false])('resets record navigation only for named-user switching (trusted=%s)', async trusted => {
  vi.spyOn(api, 'session').mockResolvedValue({ ...session, trusted_development: trusted });
  vi.spyOn(api, 'entities').mockResolvedValue({ items: [session.entity, { id: 'beta', name: 'Beta' }] });
  vi.spyOn(api, 'selectEntity').mockResolvedValue({ ...session, trusted_development: trusted, entity: { id: 'beta', name: 'Beta' } });
  const resetRoute = vi.fn();
  function Feature() {
    const current = useEntity();
    const selection = useContext(EntitySelectionContext)!;
    return <><p>Selected: {current.entity.name}</p><button onClick={() => void selection.select('beta')}>Switch route scope</button></>;
  }
  render(<ContextBoundary onScopeChange={resetRoute}><Feature /></ContextBoundary>);
  fireEvent.click(await screen.findByRole('button', { name: 'Switch route scope' }));
  expect(await screen.findByText('Selected: Beta')).toBeVisible();
  expect(resetRoute).toHaveBeenCalledTimes(trusted ? 0 : 1);
});

it('discards private drafts on a cross-tab scope signal and ignores a late switch error after logout', async () => {
  const channels = authChannel();
  vi.spyOn(api, 'session').mockResolvedValue({ ...session, trusted_development: false });
  vi.spyOn(api, 'entities').mockResolvedValue({ items: [session.entity] });
  let reject!: (error: unknown) => void;
  vi.spyOn(api, 'selectEntity').mockReturnValue(new Promise((_, fail) => { reject = fail; }));
  function Feature() {
    const selection = useContext(EntitySelectionContext)!;
    return <><input aria-label="Peer draft" defaultValue="" />
      <button onClick={() => void selection.select('beta')}>Switch peer business</button></>;
  }
  render(<ContextBoundary><Feature /></ContextBoundary>);
  fireEvent.change(await screen.findByLabelText('Peer draft'), { target: { value: 'Old draft' } });
  act(() => channels[0].onmessage?.({ data: 'scope-changed' }));
  expect(await screen.findByLabelText('Peer draft')).toHaveValue('');
  fireEvent.click(screen.getByRole('button', { name: 'Switch peer business' }));
  act(() => channels[0].onmessage?.({ data: 'signed-out' }));
  await act(async () => reject(new ApiError('unavailable')));
  expect(screen.getByRole('link', { name: 'Sign in' })).toBeVisible();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
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
  const listeners = vi.spyOn(window, 'addEventListener');
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
  // The draft can render before the parent's passive effects attach listeners.
  await waitFor(() => expect(listeners).toHaveBeenCalledWith('focus', expect.any(Function)));
  cache!.setQueryData(['receipt'], 'Private cached receipt');
  fireEvent(window, new Event('focus'));
  await screen.findByRole('link', { name: 'Sign in' });
  expect(screen.queryByLabelText('Private draft')).not.toBeInTheDocument();
  await waitFor(() => expect(cache!.getQueryCache().getAll()).toHaveLength(0));
});

it('refreshes permitted choices when another workspace is revoked without changing the selected scope', async () => {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  vi.spyOn(api, 'session').mockResolvedValue({ ...session, trusted_development: false });
  vi.spyOn(api, 'entities').mockResolvedValueOnce({ items: [session.entity, { id: 'beta', name: 'Beta' }] })
    .mockResolvedValue({ items: [session.entity] });
  function Choices() {
    const selection = useContext(EntitySelectionContext)!;
    return <p>Permitted choices: {selection.items.map(item => item.name).join(', ')}</p>;
  }
  render(<ContextBoundary><Choices /></ContextBoundary>);
  await screen.findByText('Permitted choices: Alpha, Beta');
  fireEvent(window, new Event('focus'));
  expect(await screen.findByText('Permitted choices: Alpha')).toBeVisible();
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

it('replaces private scope when validation recovers to another authorized business', async () => {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  vi.spyOn(api, 'session').mockResolvedValueOnce({ ...session, trusted_development: false })
    .mockResolvedValue({ ...session, organization_id: 'other-org',
      entity: { id: 'beta', name: 'Beta' }, trusted_development: false });
  vi.spyOn(api, 'entities').mockResolvedValue({ items: [session.entity, { id: 'beta', name: 'Beta' }] });
  const caches: QueryClient[] = [];
  function Feature() {
    const cache = useQueryClient();
    if (!caches.includes(cache)) caches.push(cache);
    return <input aria-label="Recovery draft" defaultValue="" />;
  }
  render(<ContextBoundary><Feature /></ContextBoundary>);
  fireEvent.change(await screen.findByLabelText('Recovery draft'), { target: { value: 'Alpha draft' } });
  caches[0].setQueryData(['private'], 'Alpha cached data');
  fireEvent(window, new Event('focus'));
  await waitFor(() => expect(caches).toHaveLength(2));
  expect(screen.getByLabelText('Recovery draft')).toHaveValue('');
  await waitFor(() => expect(caches[0].getQueryCache().getAll()).toHaveLength(0));
  expect(caches[1].getQueryData(['private'])).toBeUndefined();
});

it('offers outage logout with only the retained CSRF token after clearing private scope', async () => {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  vi.spyOn(api, 'session').mockResolvedValueOnce({ ...session, trusted_development: false })
    .mockRejectedValue(new ApiError('unavailable'));
  vi.spyOn(api, 'entities').mockResolvedValue({ items: [session.entity] });
  const logout = vi.spyOn(api, 'logout').mockRejectedValue(new ApiError('unavailable'));
  let cache: QueryClient | undefined;
  function Feature() {
    cache = useQueryClient();
    return <input aria-label="Outage draft" defaultValue="Private draft" />;
  }
  render(<ContextBoundary><Feature /></ContextBoundary>);
  await screen.findByLabelText('Outage draft');
  cache!.setQueryData(['private'], 'Private ledger');
  fireEvent(window, new Event('focus'));
  const signOut = await screen.findByRole('button', { name: 'Sign out' });
  expect(screen.queryByLabelText('Outage draft')).not.toBeInTheDocument();
  await waitFor(() => expect(cache!.getQueryCache().getAll()).toHaveLength(0));
  fireEvent.click(signOut);
  await screen.findByRole('link', { name: 'Sign in' });
  expect(logout).toHaveBeenCalledWith({ csrf_token: session.csrf_token });
  expect(screen.getByRole('alert')).toBeVisible();
});

it('offers logout bootstrap on an initial outage without composing private UI', async () => {
  vi.spyOn(api, 'session').mockRejectedValue(new ApiError('unavailable'));
  const entities = vi.spyOn(api, 'entities');
  const logout = vi.spyOn(api, 'logout').mockResolvedValue(undefined);
  render(<ContextBoundary><p>Private ledger</p></ContextBoundary>);
  fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }));
  await screen.findByRole('link', { name: 'Sign in' });
  expect(logout).toHaveBeenCalledWith(undefined);
  expect(screen.queryByText('Private ledger')).not.toBeInTheDocument();
  expect(entities).not.toHaveBeenCalled();
});
