import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { EmptyState, ErrorNotice, LoadingState } from '../../components/States';
import type { Session } from '../../api/client';

export function RecordList<R extends { id: string }>({ resource, title, list, label, editor, canEdit = () => true, columns = [], receiptTarget }: {
  resource: string; title: string; list: (session: Session, signal?: AbortSignal) => Promise<{ items: R[] }>;
  label: (row: R) => string; editor: (row: R, close: () => void) => ReactNode; canEdit?: (row: R) => boolean;
  receiptTarget?: (row: R) => boolean;
  columns?: { title: string; render: (row: R, rows: R[]) => ReactNode }[];
}) {
  const session = useEntity();
  const [selected, setSelected] = useState<R>();
  const query = useQuery({ queryKey: resourceKey(session, resource), queryFn: ({ signal }) => list(session, signal) });
  return <section><h2>{title}</h2>
    {selected ? <>{editor(selected, () => setSelected(undefined))}</> : query.isPending ? <LoadingState />
      : query.isError ? <ErrorNotice error={query.error} onReview={() => void query.refetch()} />
      : query.data.items.length === 0 ? <EmptyState title="No records to edit" />
      : <div className="tableScroll" role="region" aria-label={title} tabIndex={0}><table><caption>{title}</caption>
        <thead><tr><th scope="col">Record</th>{columns.map(column => <th key={column.title} scope="col">{column.title}</th>)}<th scope="col">Actions</th></tr></thead>
        <tbody>{query.data.items.map(row => <tr key={row.id}><th scope="row">{label(row)}</th>
          {columns.map(column => <td key={column.title}>{column.render(row, query.data.items)}</td>)}<td>{canEdit(row) && session.capabilities.includes('bookkeeping:write')
          && <button type="button" onClick={() => setSelected(structuredClone(row))}>Edit {label(row)}</button>}
          {receiptTarget?.(row) && <Link to={'/transactions/' + encodeURIComponent(row.id) + '/receipts'}>Receipts for {label(row)}</Link>}</td>
        </tr>)}</tbody></table></div>}
  </section>;
}
