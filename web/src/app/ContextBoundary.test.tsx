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
