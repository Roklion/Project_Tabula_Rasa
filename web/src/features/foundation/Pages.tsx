import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { accountQuery } from '../../api/query';
import { EmptyState, ErrorNotice, LoadingState } from '../../components/States';
import { useEntity } from '../../app/context';
import { useState } from 'react';
import type { Account } from '../../api/client';
import { AccountEditor } from '../concurrency/ReferenceEditors';

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
  return <><h1>Accounts</h1><p className="lead">Accounts for {session.entity.name}.</p>
    {!selected && session.capabilities.includes('bookkeeping:write') && <Link to="/accounts/new" className="button">Add account</Link>}
    {selected ? <AccountEditor row={selected} onClose={() => setSelected(undefined)} /> : query.isPending ? <LoadingState label="Loading accounts…" />
      : query.isError ? <ErrorNotice error={query.error} onReview={() => void query.refetch()} />
      : query.data.items.length === 0 ? <EmptyState title="No accounts yet">Add an account to start bookkeeping.</EmptyState>
      : <div className="tableScroll" role="region" aria-label="Accounts" tabIndex={0}><table>
        <caption>Business accounts</caption><thead><tr><th>Name</th><th>Type</th><th>Classification</th><th>Parent account</th><th>Opening balance</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>{query.data.items.map(account => <tr key={account.id}><th scope="row">{account.name}</th>
          <td>{account.type}</td><td>{account.classification}</td><td>{query.data.items.find(parent => parent.id === account.parent_id)?.name ?? '—'}</td><td className="amount">{account.opening_balance}</td>
          <td>{account.active ? 'Active' : 'Inactive'}</td><td>{session.capabilities.includes('bookkeeping:write') &&
            <button type="button" onClick={() => setSelected(structuredClone(account))}>Edit {account.name}</button>}</td></tr>)}</tbody></table></div>}
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
