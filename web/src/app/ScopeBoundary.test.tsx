import { useState } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { ScopeBoundary } from './ScopeBoundary';
import { session } from '../test/fixtures';
import { resourceKey } from '../api/query';

it('clears the previous private cache and remounts drafts when server entity/session context changes', () => {
  const caches: QueryClient[] = [];
  function Feature() {
    const cache = useQueryClient();
    if (!caches.includes(cache)) caches.push(cache);
    const [draft, setDraft] = useState('');
    return <input aria-label="Draft" value={draft} onChange={event => setDraft(event.target.value)} />;
  }
  const { rerender, unmount } = render(<ScopeBoundary session={session}><Feature /></ScopeBoundary>);
  caches[0].setQueryData(resourceKey(session, 'accounts'), { private: 'alpha ledger' });
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'alpha draft' } });
  rerender(<ScopeBoundary session={{ ...session, entity: { id: 'beta', name: 'Beta' } }}><Feature /></ScopeBoundary>);
  expect(screen.getByRole('textbox')).toHaveValue('');
  expect(caches[0].getQueryCache().getAll()).toHaveLength(0);
  expect(caches[1].getQueryCache().getAll()).toHaveLength(0);
  rerender(<ScopeBoundary session={{ ...session, cache_scope: 'new-session' }}><Feature /></ScopeBoundary>);
  expect(caches).toHaveLength(3);
  unmount();
  expect(caches[2].getQueryCache().getAll()).toHaveLength(0);
});
