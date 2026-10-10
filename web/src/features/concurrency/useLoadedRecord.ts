import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { Session } from '../../api/client';
import { resourceKey } from '../../api/query';

// The detail component must be keyed by record ID. Wait for this visit's read,
// then leave the loaded form mounted through background refetch failures.
export function useLoadedRecord<R>(session: Session, resource: string, id: string,
  read: (session: Session, id: string, signal?: AbortSignal) => Promise<R>) {
  const [initialized, setInitialized] = useState(false);
  const query = useQuery({ queryKey: [...resourceKey(session, resource), id],
    queryFn: ({ signal }) => read(session, id, signal), staleTime: 0, refetchOnMount: 'always' });
  if (!initialized && query.isFetchedAfterMount && query.isSuccess) setInitialized(true);
  return { ...query, initialized, initializing: !initialized && (!query.isFetchedAfterMount || query.isFetching) };
}
