import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { ErrorNotice, Field, LoadingState } from '../../components/States';

export function ReportsPage({ dashboard = false }: { dashboard?: boolean }) {
  const session = useEntity();
  const [filters, setFilters] = useState<{ start?: string; end?: string }>({});
  const query = useQuery({ queryKey: [...resourceKey(session, 'reports'), filters], queryFn: ({ signal }) => api.reports(session, filters, signal) });
  const report = query.data;
  return <><h1>{dashboard ? 'Dashboard' : 'Reports'}</h1><p className="lead">Bookkeeping summary for {session.entity.name}.</p>
    {dashboard && <div className="actions"><Link to="/accounts" className="button">Set up accounts</Link><Link to="/transactions">View ledger</Link></div>}
    <div className="filterGrid">
      <Field id="report-from" label="From"><input id="report-from" type="date" value={filters.start ?? ''} onChange={event => setFilters({ ...filters, start: event.target.value || undefined })} /></Field>
      <Field id="report-to" label="To / balance sheet as of"><input id="report-to" type="date" value={filters.end ?? ''} onChange={event => setFilters({ ...filters, end: event.target.value || undefined })} /></Field>
    </div>
    {query.isPending ? <LoadingState label="Loading reports…" /> : query.isError ? <ErrorNotice error={query.error} onReview={() => void query.refetch()} /> : report && <>
      <h2>Profit and loss</h2><p className="muted">Inclusive selected period. Transfers and mileage do not affect income or expenses.</p>
      <dl className="metrics">{(['income', 'expenses', 'net'] as const).map(key => <div key={key}><dt>{key === 'net' ? 'Net income' : key === 'income' ? 'Income' : 'Expenses'}</dt><dd className="amount">{report.profit_loss[key]}</dd></div>)}</dl>
      <h2>Balance sheet</h2><p className="muted">Through the To date, including opening balances and current earnings.</p>
      <dl className="metrics">{(['total_assets', 'total_liabilities', 'total_equity', 'current_earnings', 'difference'] as const).map(key => <div key={key}><dt>{({ total_assets: 'Assets', total_liabilities: 'Liabilities', total_equity: 'Equity', current_earnings: 'Current earnings', difference: 'Assets − Liabilities − Equity' })[key]}</dt><dd className="amount">{report.balance_sheet[key]}</dd></div>)}</dl>
      <p role="status" className={'notice ' + (report.balance_sheet.difference === '0.00' ? 'success' : 'warning')}>{report.balance_sheet.difference === '0.00' ? 'Assets = Liabilities + Equity.' : 'The balance sheet has a difference. Review opening balances and ledger entries.'}</p>
      {(['assets', 'liabilities', 'equity'] as const).map(section => <div key={section} className="tableScroll" role="region" aria-label={section} tabIndex={0}><table><caption>{section[0].toUpperCase() + section.slice(1)}</caption><thead><tr><th>Account</th><th>Direct balance</th><th>Including children</th></tr></thead>
        <tbody>{report.balance_sheet[section].map(row => <tr key={row.id}><th scope="row">{row.name}</th><td className="amount">{row.direct_balance}</td><td className="amount">{row.rollup_balance}</td></tr>)}</tbody></table></div>)}
      <div className="tableScroll" role="region" aria-label="Current account balances" tabIndex={0}><table><caption>Current account balances · all dates</caption><thead><tr><th>Account</th><th>Classification</th><th>Status</th><th>Ledger balance</th></tr></thead><tbody>{report.account_balances.map(row => <tr key={row.id}><th scope="row">{row.name}</th><td>{row.classification}</td><td>{row.active ? 'Active' : 'Inactive'}</td><td className="amount">{row.balance}</td></tr>)}</tbody></table></div>
    </>}
  </>;
}
