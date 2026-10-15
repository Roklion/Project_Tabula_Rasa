import { FilePicker } from '../../components/FilePicker';
import { useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, ApiError, type Schemas } from '../../api/client';
import { useEntity } from '../../app/context';
import { ErrorNotice, LoadingState, SuccessNotice } from '../../components/States';
import { ActionButton, SectionHeader, TableRegion } from '../../components/VisualPrimitives';

type CsvPreview = Schemas['TransactionCsvPreview'];
type QuickBooksPreview = Schemas['QuickBooksImportPreview'];

function SourceRows({ preview, label }: { preview: CsvPreview; label: string }) {
  return <TableRegion label={label}><table><caption>{label} · showing {preview.source_rows.length} of {preview.total_rows} rows</caption>
    <thead><tr>{preview.columns.map(column => <th scope="col" key={column}>{column}</th>)}</tr></thead>
    <tbody>{preview.source_rows.map((row, index) => <tr key={index}>{preview.columns.map(column => <td key={column}>{row[column]}</td>)}</tr>)}</tbody>
  </table></TableRegion>;
}

function Diagnostics({ title, messages }: { title: string; messages: string[] }) {
  return messages.length > 0 && <div role="alert" className="notice error"><p>{title}</p><ul>{messages.map((message, index) => <li key={index}>{message}</li>)}</ul></div>;
}

function ImportWorkflow({ quickbooks = false, onDirtyChange }: { quickbooks?: boolean; onDirtyChange: (dirty: boolean) => void }) {
  const session = useEntity();
  const cache = useQueryClient();
  const requestNumber = useRef(0);
  const [file, setFile] = useState<File>();
  const [autoCreate, setAutoCreate] = useState(false);
  const [preview, setPreview] = useState<CsvPreview | QuickBooksPreview>();
  const [failure, setFailure] = useState<unknown>();
  const [result, setResult] = useState<Schemas['TransactionImportResult']>();
  const [uncertain, setUncertain] = useState(false);
  const preparation = useMutation({
    mutationFn: ({ uploaded, createReferences }: { uploaded: File; createReferences: boolean }) => quickbooks
      ? api.previewQuickBooksTransactions(session, uploaded, createReferences) : api.prepareTransactionCsv(session, uploaded),
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: (uploaded: File) => quickbooks ? api.importQuickBooksTransactions(session, uploaded, autoCreate)
      : api.importTransactionCsv(session, uploaded),
    retry: false,
    onSettled: () => cache.invalidateQueries({ queryKey: ['private', session.cache_scope, session.entity.id] }),
  });
  const pending = preparation.isPending || mutation.isPending;
  const title = quickbooks ? 'Import QuickBooks transactions' : 'Import Project Tabula Rasa CSV';
  const qb = quickbooks ? preview as QuickBooksPreview | undefined : undefined;
  useEffect(() => onDirtyChange(Boolean(file) && !result), [file, result, onDirtyChange]);

  async function prepare(selected: File | undefined, createReferences = autoCreate) {
    const current = ++requestNumber.current;
    setFile(selected); setPreview(undefined); setResult(undefined); setFailure(undefined);
    if (!selected) return;
    try {
      const loaded = await preparation.mutateAsync({ uploaded: selected, createReferences });
      if (current === requestNumber.current) { setPreview(loaded); setUncertain(false); }
    } catch (error) {
      if (current === requestNumber.current) setFailure(error);
    }
  }

  async function commit() {
    if (!file || !preview || pending || uncertain) return;
    setFailure(undefined);
    try {
      const imported = await mutation.mutateAsync(file);
      setResult(imported); setPreview(undefined);
    } catch (error) {
      setFailure(error);
      setUncertain(!(error instanceof ApiError && ['validation', 'reference', 'invariant', 'required',
        'conflict', 'duplicate', 'concurrent_write', 'forbidden', 'unauthorized'].includes(error.code)));
    }
  }

  const blocked = !preview || (preview.errors?.length ?? 0) > 0 || pending || uncertain || (qb
    ? qb.errors.length > 0 || qb.conversion_errors.length > 0 || qb.summary.ready === 0 : preview.total_rows === 0);
  return <section className="surface editor" aria-label={title}>
    <SectionHeader title={title} description={quickbooks
      ? 'Upload a QuickBooks Online Transaction Detail by Account CSV, or a QuickBooks Self-Employed General ledger XLSX or ZIP export. Review the results before importing.'
      : 'Required columns: Date, Type, Amount, Account, Category. Optional columns: Payee, Description, Reference. Type must be Income or Expense.'} />
    <p className="muted">Selected business: {session.entity.name}. Each file is limited to 25 MB and 1,000 rows; split larger sources into batches.</p>
    <fieldset disabled={mutation.isPending || uncertain}>
      <FilePicker id={quickbooks ? 'quickbooks-transactions-file' : 'tabula-transactions-file'}
        label={quickbooks ? 'QuickBooks export' : 'Transaction CSV file'} accept={quickbooks ? '.csv,.xlsx,.zip' : '.csv'}
        disabled={mutation.isPending || uncertain} onFiles={files => void prepare(files[0])} />
      {quickbooks && <><label className="checkbox"><input type="checkbox" checked={autoCreate} onChange={event => {
        setAutoCreate(event.target.checked); void prepare(file, event.target.checked);
      }} /> Automatically create missing accounts and categories</label>
      <p className="muted">New accounts use an inferred type and classification with zero opening balance. New categories infer Income or Expense from the amount.</p></>}
    </fieldset>
    {pending && <LoadingState label={preparation.isPending ? 'Preparing import…' : 'Importing transactions…'} />}
    {failure !== undefined && <><ErrorNotice error={failure} />
      {!uncertain && <p>Check the file headers, dates, amounts, and account/category references, then review the file again before importing. A failed batch is not reported as a partial import.</p>}</>}
    {uncertain && <p role="alert">Import confirmation is unavailable. <Link to="/transactions">Review the transaction ledger</Link> before resubmitting. The same file retains its batch identity; no automatic retry was made.</p>}
    {result && <SuccessNotice>{result.imported_count > 0 ? `Imported ${result.imported_count} transactions.`
      : 'No new transactions were imported. This submitted batch may already be complete.'}</SuccessNotice>}
    {preview && !quickbooks && <Diagnostics title="Fix these CSV file errors before continuing:" messages={preview.errors ?? []} />}
    {qb && <>
      <dl className="metrics reportMetrics">{([['Ready', qb.summary.ready], ['Duplicates', qb.summary.duplicates], ['Income', qb.summary.Income],
        ['Expenses', qb.summary.Expense], ['Transfers', qb.summary.Transfer], ['Validation errors', qb.summary.validation_errors],
        ['Conversion errors', qb.summary.conversion_errors]] as const).map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count}</dd></div>)}</dl>
      <Diagnostics title="Fix these import errors before continuing:" messages={qb.errors} />
      <Diagnostics title="Some QuickBooks rows could not be converted:" messages={qb.conversion_errors} />
      {qb.duplicate_rows.length > 0 && <p className="notice warning">Already imported or repeated rows will be skipped: {qb.duplicate_rows.join(', ')}.</p>}
      {autoCreate && (qb.new_accounts.length > 0 || qb.new_categories.length > 0) && <div className="notice neutral"><p>Will create:</p><ul>
        {qb.new_accounts.map(account => <li key={account.name}>Account: {account.name} · Classification: {account.classification} · Type: {account.type} · Opening balance: {account.opening_balance}</li>)}
        {qb.new_categories.map(category => <li key={category.kind + ':' + category.name}>{category.kind} category: {category.name}</li>)}
      </ul></div>}
    </>}
    {preview && <SourceRows preview={preview} label={quickbooks ? 'QuickBooks source rows' : 'Tabula Rasa source rows'} />}
    {preview && <p>Import writes one confirmed batch after checking references again. {quickbooks ? 'Duplicate rows are skipped. Transfers do not affect income or expenses.' : 'Only Income and Expense rows are supported.'}</p>}
    <div className="actions"><ActionButton tone="primary" disabled={blocked} onClick={() => void commit()}>
      {quickbooks ? 'Import validated rows' : 'Import rows'}</ActionButton>
      {file && <ActionButton disabled={pending} onClick={() => void prepare(file)}>Review this file again</ActionButton>}
    </div>
  </section>;
}

export function TransactionImportsPage({ onDirtyChange }: { onDirtyChange?: (dirty: boolean) => void }) {
  const session = useEntity();
  const [csvDirty, setCsvDirty] = useState(false);
  const [quickBooksDirty, setQuickBooksDirty] = useState(false);
  useEffect(() => onDirtyChange?.(csvDirty || quickBooksDirty), [csvDirty, quickBooksDirty, onDirtyChange]);
  if (!session.capabilities.includes('bookkeeping:write')) return <p>Bookkeeping write access is required to prepare and import transaction files.</p>;
  return <><ImportWorkflow onDirtyChange={setCsvDirty} /><ImportWorkflow quickbooks onDirtyChange={setQuickBooksDirty} /></>;
}
