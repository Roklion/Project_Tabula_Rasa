import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { accountQuery } from '../../api/query';
import { EmptyState, ErrorNotice, LoadingState } from '../../components/States';
import { useEntity } from '../../app/context';
import { useState } from 'react';
import type { Account } from '../../api/client';
import { AccountEditor } from '../concurrency/ReferenceEditors';
import { ActionButton, PageHeader, TableRegion } from '../../components/VisualPrimitives';

export function Dashboard() {
  const session = useEntity();
  return <><p className="eyebrow">Your workspace</p><h1>Dashboard</h1>
    <p className="lead">A clear view of {session.entity.name}.</p>
    <section className="surface"><h2>Start with your accounts</h2>
      <p>Review the accounts connected to this business.</p><Link to="/accounts" className="button">View accounts</Link>
    </section></>;
}

export function Accounts() {
  const session = useEntity();
  const [selected, setSelected] = useState<Account>();
  const query = useQuery(accountQuery(session));
  return <><PageHeader title="Accounts" description={<>Accounts for {session.entity.name}.</>}
    actions={!selected && session.capabilities.includes('bookkeeping:write') && <Link to="/accounts/new" className="button">Add account</Link>} />
    {selected ? <AccountEditor row={selected} onClose={() => setSelected(undefined)} /> : query.isPending ? <LoadingState label="Loading accounts…" />
      : query.isError ? <ErrorNotice error={query.error} onReview={() => void query.refetch()} />
      : query.data.items.length === 0 ? <EmptyState title="No accounts yet">Add an account to start bookkeeping.</EmptyState>
      : <TableRegion label="Accounts"><table>
        <caption>Business accounts</caption><thead><tr><th scope="col">Name</th><th scope="col">Type</th><th scope="col">Classification</th><th scope="col">Parent account</th><th scope="col" className="amount">Opening balance</th><th scope="col">Status</th><th scope="col">Actions</th></tr></thead>
        <tbody>{query.data.items.map(account => <tr key={account.id}><th scope="row" className="tableText">{account.name}</th>
          <td>{account.type}</td><td>{account.classification}</td><td className="tableText">{query.data.items.find(parent => parent.id === account.parent_id)?.name ?? '—'}</td><td className="amount">{account.opening_balance}</td>
          <td>{account.active ? 'Active' : 'Inactive'}</td><td>{session.capabilities.includes('bookkeeping:write') &&
            <ActionButton aria-label={'Edit ' + account.name} onClick={() => setSelected(structuredClone(account))}>Edit</ActionButton>}</td></tr>)}</tbody></table></TableRegion>}
  </>;
}

export function PlannedPage({ title }: { title: string }) {
  return <><h1>{title}</h1><EmptyState title="This workspace is taking shape">
    This workflow will be available in a later technical alpha release.
  </EmptyState></>;
}

export function MissingPage() {
  return <><h1>Page not found</h1><p>Choose a page from the navigation.</p><Link to="/">Return to dashboard</Link></>;
}

export function RouteError() {
  return <main className="standalone"><h1>Page unavailable</h1><ErrorNotice error={undefined} /><a href="/">Return to dashboard</a></main>;
}
