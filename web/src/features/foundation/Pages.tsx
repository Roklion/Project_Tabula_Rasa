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
      : query.isError ? <ErrorNotice error={query.error} operation="read" onReview={() => void query.refetch()} />
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
  return <><PageHeader title={title} /><EmptyState title="Not available in this technical alpha">
    {title === 'Data & backup' ? 'Import and backup controls are not available on this commercial page. Mileage CSV is available from Mileage.' : 'This workflow is not available in this commercial workspace.'}
  </EmptyState></>;
}

export function MissingPage() {
  return <><PageHeader title="Page not found" description="Choose a page from the navigation." /><Link className="button action-secondary" to="/">Return to dashboard</Link></>;
}

export function RouteError() {
  return <main className="standalone"><PageHeader title="Page unavailable" /><ErrorNotice error={undefined} operation="read" /><a className="button action-secondary" href="/">Return to dashboard</a></main>;
}
