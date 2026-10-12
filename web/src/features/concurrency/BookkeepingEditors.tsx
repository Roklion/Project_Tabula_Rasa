import { PageHeader } from '../../components/VisualPrimitives';
import { Link } from 'react-router-dom';
import { useFieldArray, type UseFormReturn } from 'react-hook-form';
import { api, type Schemas } from '../../api/client';
import { useEntity } from '../../app/context';
import { ErrorNotice, LoadingState } from '../../components/States';
import { ProtectedEditor } from './ProtectedEditor';
import { RecordList } from './RecordList';
import { latest } from './mutations';
import { SelectField, TextField } from './Fields';
import { activeChoices, useReferenceChoices } from './useReferenceChoices';
import { journalTotals } from '../workflows/journalDraft';

const options = (values: string[]) => values.map(value => ({ id: value, name: value }));
const blank = { id: '', name: 'None' };
const metadata = (row: { id: string; baseline: string }) => ({ id: row.id, baseline: row.baseline });

function transactionLoaded(row: Schemas['Transaction']) {
  const values: Schemas['TransactionChanges'] = { txn_date: row.txn_date, kind: row.kind, amount: row.amount,
    account_id: row.account_id, to_account_id: row.to_account_id, category_id: row.category_id,
    payee_id: row.payee_id, tag_ids: row.tag_ids, description: row.description, reference: row.reference,
    new_payee_name: '', new_tag_name: '' };
  return { values, metadata: metadata(row) };
}

export function TransactionFields({ form, creating = false }: { form: UseFormReturn<Schemas['TransactionChanges']>; creating?: boolean }) {
  const session = useEntity();
  const choices = useReferenceChoices(session);
  const original = form.formState.defaultValues;
  const kind = form.watch('kind');
  const accounts = activeChoices(choices.accounts, creating ? [] : [original?.account_id]);
  const source = form.watch('account_id');
  if (choices.pending) return <LoadingState label="Loading choices…" />;
  if (choices.error) return <ErrorNotice error={choices.error} />;
  return <><SelectField form={form} name="kind" label="Type" options={options(['Income', 'Expense', 'Transfer'])}
    onChange={() => {
      const nextKind = form.getValues('kind');
      if (nextKind !== 'Transfer' && choices.categories.find(category => category.id === form.getValues('category_id'))?.kind !== nextKind) {
        form.setValue('category_id', '', { shouldDirty: true });
      }
    }} />
    {creating && (accounts.length === 0 || (kind !== 'Transfer' && !choices.categories.some(row => row.kind === kind))) &&
      <p role="alert">Set up an active account and a matching category before saving. Transfers require two active accounts.</p>}
    <TextField form={form} name="txn_date" label="Date" type="date" />
    <TextField form={form} name="amount" label="Amount" />
    <SelectField form={form} name="account_id" label={kind === 'Income' ? 'To account' : 'From account'} options={[blank, ...accounts]}
      onChange={() => {
        if (form.getValues('account_id') === form.getValues('to_account_id')) form.setValue('to_account_id', '', { shouldDirty: true });
      }} />
    {kind === 'Transfer' ? <SelectField form={form} name="to_account_id" label="To account" options={[blank, ...activeChoices(choices.accounts, [original?.to_account_id]).filter(account => account.id !== source)]} />
      : <SelectField form={form} name="category_id" label="Category" options={[blank, ...choices.categories.filter(row => row.kind === kind)]} />}
    <SelectField form={form} name="payee_id" label="Payee / customer" options={[blank, ...activeChoices(choices.payees, [original?.payee_id])]}
      onChange={() => { if (form.getValues('payee_id')) form.setValue('new_payee_name', '', { shouldDirty: true }); }} />
    <TextField form={form} name="new_payee_name" label="New payee name (optional)"
      onChange={() => { if (form.getValues('new_payee_name').trim()) form.setValue('payee_id', '', { shouldDirty: true }); }} />
    <SelectField form={form} name="tag_ids" label="Tags" options={activeChoices(choices.tags, original?.tag_ids ?? [])} multiple />
    <TextField form={form} name="new_tag_name" label="New tag name (optional)" />
    <TextField form={form} name="description" label="Description / memo" />
    <TextField form={form} name="reference" label="Reference" /></>;
}

export function TransactionEditor({ row, onClose }: { row: Schemas['Transaction']; onClose: () => void }) {
  const session = useEntity();
  return <ProtectedEditor session={session} loaded={transactionLoaded(row)} title="Edit transaction" onClose={onClose}
    save={async (id, baseline, changes) => transactionLoaded(await api.updateTransaction(session, id, { baseline, changes: { ...changes,
      to_account_id: changes.kind === 'Transfer' ? changes.to_account_id : '',
      category_id: changes.kind === 'Transfer' ? '' : changes.category_id } }))}
    remove={(id, baseline) => api.deleteTransaction(session, id, baseline)}
    loadLatest={async id => transactionLoaded(await latest(api.transactions, session, id))}
    fields={form => <TransactionFields form={form} />} />;
}

function journalLoaded(row: Schemas['Journal']) {
  const values: Schemas['JournalChanges'] = { txn_date: row.txn_date, description: row.description, postings: row.postings };
  return { values, metadata: metadata(row) };
}

export function JournalFields({ form, creating = false }: { form: UseFormReturn<Schemas['JournalChanges']>; creating?: boolean }) {
  const session = useEntity();
  const choices = useReferenceChoices(session);
  const lines = useFieldArray({ control: form.control, name: 'postings', keyName: 'formKey' });
  const totals = journalTotals(form.watch('postings'));
  if (choices.pending) return <LoadingState label="Loading choices…" />;
  if (choices.error) return <ErrorNotice error={choices.error} />;
  return <><TextField form={form} name="txn_date" label="Date" type="date" />
    <TextField form={form} name="description" label="Description / memo" />
    {lines.fields.map((line, index) => {
      const original = creating ? undefined : form.formState.defaultValues?.postings?.find(posting => posting?.id === line.id);
      const accounts = activeChoices(choices.accounts, [original?.target_type === 'account' ? original.target_id : undefined]);
      const payees = activeChoices(choices.payees, [original?.payee_id]);
      return <div className="posting" key={line.formKey}>
      <h3>Posting {index + 1}</h3>
      <SelectField form={form} name={`postings.${index}.target_type`} label="Account or category" options={options(['account', 'category'])}
        onChange={() => form.setValue(`postings.${index}.target_id`, '', { shouldDirty: true })} />
      <SelectField form={form} name={`postings.${index}.target_id`} label="Target" options={[{ id: '', name: 'Choose target' }, ...(form.watch(`postings.${index}.target_type`) === 'account' ? accounts : choices.categories)]} />
      <SelectField form={form} name={`postings.${index}.side`} label="Side" options={options(['Debit', 'Credit'])} />
      <TextField form={form} name={`postings.${index}.amount`} label="Amount" />
      <SelectField form={form} name={`postings.${index}.payee_id`} label="Payee / customer" options={[blank, ...payees]} />
      <TextField form={form} name={`postings.${index}.description`} label="Description" />
      <button type="button" disabled={lines.fields.length <= 2} onClick={() => lines.remove(index)}>Remove posting {index + 1}</button>
    </div>; })}
    <button type="button" onClick={() => lines.append({ id: crypto.randomUUID(), target_type: 'account', target_id: '', side: 'Debit', amount: '0.00', payee_id: '', description: '' })}>Add posting</button>
    <p role="status">Total Debits: {totals.debit} · Total Credits: {totals.credit} · Difference: {totals.difference}</p>
    <p className="muted">Debits and credits must balance. Saving validates the complete journal.</p>
  </>;
}

export function JournalEditor({ row, onClose }: { row: Schemas['Journal']; onClose: () => void }) {
  const session = useEntity();
  return <ProtectedEditor session={session} loaded={journalLoaded(row)} title="Edit journal" onClose={onClose}
    save={async (id, baseline, changes) => journalLoaded(await api.updateJournal(session, id, { baseline, changes }))}
    remove={(id, baseline) => api.deleteJournal(session, id, baseline)}
    loadLatest={async id => journalLoaded(await latest(api.journals, session, id))}
    fields={form => <JournalFields form={form} />} />;
}

export function BookkeepingPage({ resource }: { resource: 'transactions' | 'journals' }) {
  const session = useEntity();
  const title = resource[0].toUpperCase() + resource.slice(1);
  return <><PageHeader title={title} description="Review existing records and save changes for this business."
    actions={session.capabilities.includes('bookkeeping:write') && <Link className="button" to={'/' + resource + '/new'}>Add {resource === 'transactions' ? 'transaction' : 'journal'}</Link>} />
    {resource === 'transactions' ? <RecordList key={resource} resource={resource} title="Transactions" list={api.transactions}
      label={row => `${row.txn_date} · ${row.description || row.kind} · ${row.amount}`} canEdit={row => !row.source_type} receiptTarget={row => !row.source_type}
      editor={(row, close) => <TransactionEditor row={row} onClose={close} />} />
      : <RecordList key={resource} resource={resource} title="Journals" list={api.journals}
        label={row => `${row.txn_date} · ${row.description || 'Journal'}`} editor={(row, close) => <JournalEditor row={row} onClose={close} />} />}
  </>;
}
