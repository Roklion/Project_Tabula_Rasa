import { useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { EmptyState, ErrorNotice, LoadingState } from '../../components/States';
import type { Session } from '../../api/client';

export function RecordList<R extends { id: string }>({ resource, title, list, label, editor, canEdit = () => true }: {
  resource: string; title: string; list: (session: Session, signal?: AbortSignal) => Promise<{ items: R[] }>;
  label: (row: R) => string; editor: (row: R, close: () => void) => ReactNode; canEdit?: (row: R) => boolean;
}) {
  const session = useEntity();
  const [selected, setSelected] = useState<R>();
  const query = useQuery({ queryKey: resourceKey(session, resource), queryFn: ({ signal }) => list(session, signal) });
  return <section><h2>{title}</h2>
    {selected ? <>{editor(selected, () => setSelected(undefined))}</> : query.isPending ? <LoadingState />
      : query.isError ? <ErrorNotice error={query.error} onReview={() => void query.refetch()} />
      : query.data.items.length === 0 ? <EmptyState title="No records to edit" />
      : <ul className="recordList">{query.data.items.map(row => <li key={row.id}>
        <span>{label(row)}</span>{canEdit(row) && session.capabilities.includes('bookkeeping:write')
          && <button type="button" onClick={() => setSelected(structuredClone(row))}>Edit {label(row)}</button>}
      </li>)}</ul>}
  </section>;
}
