import { useEffect, useState, type ReactNode } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { Session } from '../api/client';
import { createPrivateCache } from '../api/query';
import { EntityContext } from './context';

function PrivateScope({ session, children }: { session: Session; children: ReactNode }) {
  const [cache] = useState(createPrivateCache);
  useEffect(() => () => {
    void cache.cancelQueries();
    cache.clear();
  }, [cache]);
  return <QueryClientProvider client={cache}>
    <EntityContext.Provider value={session}>{children}</EntityContext.Provider>
  </QueryClientProvider>;
}

export function ScopeBoundary({ session, children }: { session: Session; children: ReactNode }) {
  // #222 feeds refreshed membership context here. Changing scope remounts all
  // private queries and feature drafts; no result from the old scope is reused.
  const key = JSON.stringify([session.cache_scope, session.actor_id, session.organization_id,
    session.entity.id, [...session.capabilities].sort()]);
  return <PrivateScope key={key} session={session}>{children}</PrivateScope>;
}
