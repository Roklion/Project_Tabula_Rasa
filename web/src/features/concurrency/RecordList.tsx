import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { EmptyState, ErrorNotice, LoadingState } from '../../components/States';
import type { Session } from '../../api/client';
import { ActionButton, TableRegion } from '../../components/VisualPrimitives';

export function RecordList<R extends { id: string }>({ resource, title, list, label, editor, canEdit = () => true, columns = [], receiptTarget, detailsTarget }: {
  resource: string; title: string; list: (session: Session, signal?: AbortSignal) => Promise<{ items: R[] }>;
  label: (row: R) => string; editor: (row: R, close: () => void) => ReactNode; canEdit?: (row: R) => boolean;
  receiptTarget?: (row: R) => boolean;
  detailsTarget?: (row: R) => string | undefined;
  columns?: { title: string; className?: string; render: (row: R, rows: R[]) => ReactNode }[];
}) {
  const session = useEntity();
  const [selected, setSelected] = useState<R>();
  const query = useQuery({ queryKey: resourceKey(session, resource), queryFn: ({ signal }) => list(session, signal) });
  return <section><h2>{title}</h2>
    {selected ? <>{editor(selected, () => setSelected(undefined))}</> : query.isPending ? <LoadingState />
      : query.isError ? <ErrorNotice error={query.error} operation="read" onReview={() => void query.refetch()} />
      : query.data.items.length === 0 ? <EmptyState title="No records to edit">Records for this business will appear here.</EmptyState>
      : <TableRegion label={title}><table><caption>{title}</caption>
        <thead><tr><th scope="col">Record</th>{columns.map(column => <th key={column.title} scope="col" className={column.className}>{column.title}</th>)}<th scope="col">Actions</th></tr></thead>
        <tbody>{query.data.items.map(row => <tr key={row.id}><th scope="row" className="tableText">{label(row)}</th>
          {columns.map(column => <td key={column.title} className={column.className}>{column.render(row, query.data.items)}</td>)}<td className="tableActions"><div className="rowActions">{canEdit(row) && session.capabilities.includes('bookkeeping:write')
          && <ActionButton aria-label={'Edit ' + label(row)} onClick={() => setSelected(structuredClone(row))}>Edit</ActionButton>}
          {detailsTarget?.(row) && <Link className="button action-secondary" aria-label={'View ' + label(row)} to={detailsTarget(row)!}>View</Link>}
          {receiptTarget?.(row) && <Link className="button action-secondary" aria-label={'Receipts for ' + label(row)} to={'/transactions/' + encodeURIComponent(row.id) + '/receipts'}>Receipts</Link>}</div></td>
        </tr>)}</tbody></table></TableRegion>}
  </section>;
}
