import { DateRangeFields } from '../../components/DateRangeFields';
import { ActionButton, PageHeader, TableRegion } from '../../components/VisualPrimitives';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, type Schemas } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { EmptyState, ErrorNotice, Field, LoadingState } from '../../components/States';
import { JournalEditor, TransactionEditor } from '../concurrency/BookkeepingEditors';
import { latest } from '../concurrency/mutations';
import { useReferenceChoices } from '../concurrency/useReferenceChoices';

type Selection = { transaction: Schemas['Transaction'] } | { journal: Schemas['Journal'] };
const sortFields = { Date: 'txn_date', Type: 'kind', Account: 'account', Payee: 'payee', Amount: 'amount', Description: 'description', ID: 'record_id' } as const;
type Kind = 'All' | 'Income' | 'Expense' | 'Transfer' | 'Journal';

export function LedgerPage() {
  const session = useEntity();
  const choices = useReferenceChoices(session);
  const [filters, setFilters] = useState<{ start?: string; end?: string; kind: Kind; account_ids: string[]; category_ids: string[]; tag_ids: string[] }>({ kind: 'All', account_ids: [], category_ids: [], tag_ids: [] });
  const [search, setSearch] = useState('');
  const [sortField, setSortField] = useState<keyof typeof sortFields>('Date');
  const [descending, setDescending] = useState(true);
  const [selected, setSelected] = useState<Selection>();
  const [loadingRecord, setLoadingRecord] = useState(false);
  const [failure, setFailure] = useState<unknown>();
  const query = useQuery({ queryKey: [...resourceKey(session, 'ledger'), filters], queryFn: ({ signal }) => api.ledger(session, filters, signal) });
  async function edit(row: Schemas['LedgerItem']) {
    setLoadingRecord(true); setFailure(undefined);
    try {
      setSelected(row.entry_type === 'journal' ? { journal: await latest(api.journals, session, row.record_id) }
        : { transaction: await latest(api.transactions, session, row.record_id) });
    } catch (error) { setFailure(error); }
    finally { setLoadingRecord(false); }
  }
  const rows = query.data?.items.filter(row => !search.trim() || [row.kind, row.account, row.to_account, row.category, row.payee, ...row.tags,
    row.description, row.reference, row.id, ...row.postings.flatMap(line => [line.target, line.payee, line.description])]
    .some(text => text.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))) ?? [];
  rows.sort((a, b) => {
    const field = sortFields[sortField];
    const left = field === 'amount' ? BigInt(a.amount.replace('.', '')) : a[field].toLocaleLowerCase();
    const right = field === 'amount' ? BigInt(b.amount.replace('.', '')) : b[field].toLocaleLowerCase();
    const compared = left < right ? -1 : left > right ? 1 : 0;
    return descending ? -compared : compared;
  });
  const selectedTargets = [...choices.accounts.filter(row => filters.account_ids.includes(row.id)).map(row => row.name),
    ...choices.categories.filter(row => filters.category_ids.includes(row.id)).map(row => `${row.kind} category · ${row.name}`)];
  const selectedTags = choices.tags.filter(row => filters.tag_ids.includes(row.id)).map(row => row.name);
  const multi = (element: HTMLSelectElement) => Array.from(element.selectedOptions, option => option.value);
  return <><PageHeader title="Transactions" description={<>Simple transactions and complete journals for {session.entity.name}.</>}
    actions={!loadingRecord && !selected && session.capabilities.includes('bookkeeping:write') && <>
      <Link className="button" to="/transactions/new">Add transaction</Link><Link to="/journals/new" className="button action-secondary">Add journal</Link></>} />
    {loadingRecord ? <LoadingState label="Loading record…" /> : selected ? 'transaction' in selected ? <TransactionEditor row={selected.transaction} onClose={() => setSelected(undefined)} />
      : <JournalEditor row={selected.journal} onClose={() => setSelected(undefined)} /> : <>
      <section className="surface ledgerFilters" aria-label="Ledger filters"><h2>Filter ledger</h2>
      <div className="filterGrid ledgerFilterGrid">
        <DateRangeFields prefix="ledger" start={filters.start} end={filters.end}
          onStart={value => setFilters({ ...filters, start: value || undefined })} onEnd={value => setFilters({ ...filters, end: value || undefined })} />
        <Field id="kind" label="Type"><select id="kind" value={filters.kind} onChange={event => setFilters({ ...filters, kind: event.target.value as Kind })}>{['All', 'Income', 'Expense', 'Transfer', 'Journal'].map(kind => <option key={kind}>{kind}</option>)}</select></Field>
        <Field id="account-filter" label="Accounts"><select id="account-filter" multiple size={4} aria-describedby="account-filter-help" value={[...filters.account_ids.map(id => 'account:' + id), ...filters.category_ids.map(id => 'category:' + id)]} onChange={event => {
          const targets = multi(event.target);
          setFilters({ ...filters, account_ids: targets.filter(id => id.startsWith('account:')).map(id => id.slice(8)),
            category_ids: targets.filter(id => id.startsWith('category:')).map(id => id.slice(9)) });
        }}>{choices.accounts.map(row => <option key={row.id} value={'account:' + row.id}>{row.name}{row.active ? '' : ' (Inactive)'}</option>)}{choices.categories.map(row => <option key={'category:' + row.id} value={'category:' + row.id}>{row.kind} category · {row.name}</option>)}</select><p id="account-filter-help" className="fieldHint">Accounts and category targets. Select multiple with Ctrl/Command or Shift; no selection includes all.</p>{selectedTargets.length > 0 && <p className="fieldHint">Selected: {selectedTargets.join('; ')}</p>}</Field>
        <Field id="tag-filter" label="Tags"><select id="tag-filter" multiple size={4} aria-describedby="tag-filter-help" value={filters.tag_ids} onChange={event => setFilters({ ...filters, tag_ids: multi(event.target) })}>{choices.tags.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select><p id="tag-filter-help" className="fieldHint">Matches any selected tag. Select multiple with Ctrl/Command or Shift; no selection includes all.</p>{selectedTags.length > 0 && <p className="fieldHint">Selected: {selectedTags.join('; ')}</p>}</Field>
        <div className="ledgerSearch"><Field id="search" label="Search transactions"><input id="search" type="search" value={search} onChange={event => setSearch(event.target.value)} /></Field>
        {search.trim() && <ActionButton onClick={() => setSearch('')}>Clear search</ActionButton>}</div>
        <Field id="sort-field" label="Sort entries by"><select id="sort-field" value={sortField} onChange={event => setSortField(event.target.value as keyof typeof sortFields)}>{Object.keys(sortFields).map(field => <option key={field}>{field}</option>)}</select></Field>
        <Field id="entry-order" label="Entry order"><select id="entry-order" value={descending ? 'Descending' : 'Ascending'} onChange={event => setDescending(event.target.value === 'Descending')}><option>Descending</option><option>Ascending</option></select></Field>
      </div><div className="actions filterActions"><ActionButton onClick={() => { setFilters({ kind: 'All', account_ids: [], category_ids: [], tag_ids: [] }); setSearch(''); setSortField('Date'); setDescending(true); }}>Clear filters</ActionButton></div></section>
      {!query.isPending && !query.isError && <p role="status">{rows.length} matching entries</p>}
      {choices.error && <ErrorNotice error={choices.error} />}
      {failure !== undefined && <ErrorNotice error={failure} />}
      {query.isPending ? <LoadingState label="Loading ledger…" /> : query.isError ? <ErrorNotice error={query.error} onReview={() => void query.refetch()} />
        : rows.length === 0 ? <EmptyState title="No matching entries">Add an entry or adjust the filters.</EmptyState>
        : <TableRegion label="Ledger"><table className="ledgerTable"><caption>Business ledger</caption>
          <thead><tr>{['Date', 'Type', 'Account', 'To account', 'Category', 'Payee', 'Amount', 'Debit', 'Credit', 'Tags', 'Description', 'Receipt', 'Reference', 'ID', 'Actions'].map(name => <th scope="col" className={['Amount', 'Debit', 'Credit', 'Receipt'].includes(name) ? 'amount' : undefined} key={name}>{name}</th>)}</tr></thead>
          {rows.map(row => <tbody key={row.id} className={row.entry_type === 'journal' ? 'journalGroup' : undefined}><tr><td>{row.txn_date}</td><th scope="row" className="tableText">{row.kind}{row.source_type === 'mixed_use_expense' ? ' · Mixed-use' : ''}</th><td className="tableText">{row.account}</td><td className="tableText">{row.to_account}</td><td className="tableText">{row.category}</td><td className="tableText">{row.payee}</td><td className="amount">{row.amount}</td><td /><td /><td className="tableText">{row.tags.join(', ')}</td><td className="tableText">{row.description}</td><td className="amount">{row.receipt_count ? `${row.receipt_count} receipt(s)` : ''}</td><td className="tableText">{row.reference}</td><td className="ledgerIdentity">{row.record_id}</td>
            <td className="tableActions"><div className="rowActions">{row.entry_type === 'transaction' && !row.source_type && <Link className="button action-secondary" to={'/transactions/' + encodeURIComponent(row.record_id) + '/receipts'} aria-label={`Receipts for ${row.txn_date} · ${row.description || row.kind} · ${row.amount}`}>Receipts</Link>}{row.source_type === 'mixed_use_expense' ? <Link to="/mixed-use">Manage mixed-use expense</Link> : row.source_type === 'depreciation' ? <Link to="/assets">Manage in Assets</Link> : row.source_type ? 'Managed by ' + row.source_type : session.capabilities.includes('bookkeeping:write') && <ActionButton disabled={loadingRecord} aria-label={`Edit ${row.txn_date} · ${row.description || row.kind} · ${row.amount}`} onClick={() => void edit(row)}>Edit</ActionButton>}</div></td></tr>
            {row.postings.map((line, index) => <tr key={index} className="postingRow"><td /><th scope="row">↳ Posting</th><td className="tableText">{line.target}</td><td /><td /><td className="tableText">{line.payee}</td><td /><td className="amount">{line.side === 'Debit' ? line.amount : ''}</td><td className="amount">{line.side === 'Credit' ? line.amount : ''}</td><td /><td className="tableText">{line.description}</td><td colSpan={4} /></tr>)}
          </tbody>)}</table></TableRegion>}
    </>}
  </>;
}
