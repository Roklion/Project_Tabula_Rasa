import { Link } from 'react-router-dom';
import { useFieldArray, type UseFormReturn } from 'react-hook-form';
import { api, type Schemas } from '../../api/client';
import { useEntity } from '../../app/context';
import { ErrorNotice, LoadingState } from '../../components/States';
import { ProtectedEditor } from './ProtectedEditor';
import { RecordList } from './RecordList';
import { latest } from './mutations';
import { SelectField, TextField } from './Fields';
import { useReferenceChoices } from './useReferenceChoices';

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

function TransactionFields({ form }: { form: UseFormReturn<Schemas['TransactionChanges']> }) {
  const session = useEntity();
  const choices = useReferenceChoices(session);
  const kind = form.watch('kind');
  if (choices.pending) return <LoadingState label="Loading choices…" />;
  if (choices.error) return <ErrorNotice error={choices.error} />;
  return <><SelectField form={form} name="kind" label="Type" options={options(['Income', 'Expense', 'Transfer'])} />
    <TextField form={form} name="txn_date" label="Date" type="date" />
    <TextField form={form} name="amount" label="Amount" />
    <SelectField form={form} name="account_id" label={kind === 'Income' ? 'To account' : 'From account'} options={choices.accounts} />
    {kind === 'Transfer' ? <SelectField form={form} name="to_account_id" label="To account" options={[blank, ...choices.accounts]} />
      : <SelectField form={form} name="category_id" label="Category" options={[blank, ...choices.categories.filter(row => row.kind === kind)]} />}
    <SelectField form={form} name="payee_id" label="Payee / customer" options={[blank, ...choices.payees]} />
    <TextField form={form} name="new_payee_name" label="New payee name (optional)" />
    <SelectField form={form} name="tag_ids" label="Tags" options={choices.tags} multiple />
    <TextField form={form} name="new_tag_name" label="New tag name (optional)" />
    <TextField form={form} name="description" label="Description / memo" />
    <TextField form={form} name="reference" label="Reference" /></>;
}

function TransactionEditor({ row, onClose }: { row: Schemas['Transaction']; onClose: () => void }) {
  const session = useEntity();
  return <ProtectedEditor session={session} loaded={transactionLoaded(row)} title="Edit transaction" onClose={onClose}
    save={async (id, baseline, changes) => transactionLoaded(await api.updateTransaction(session, id, { baseline, changes }))}
    remove={(id, baseline) => api.deleteTransaction(session, id, baseline)}
    loadLatest={async id => transactionLoaded(await latest(api.transactions, session, id))}
    fields={form => <TransactionFields form={form} />} />;
}

function journalLoaded(row: Schemas['Journal']) {
  const values: Schemas['JournalChanges'] = { txn_date: row.txn_date, description: row.description, postings: row.postings };
  return { values, metadata: metadata(row) };
}

function JournalFields({ form }: { form: UseFormReturn<Schemas['JournalChanges']> }) {
  const session = useEntity();
  const choices = useReferenceChoices(session);
  const lines = useFieldArray({ control: form.control, name: 'postings', keyName: 'formKey' });
  if (choices.pending) return <LoadingState label="Loading choices…" />;
  if (choices.error) return <ErrorNotice error={choices.error} />;
  return <><TextField form={form} name="txn_date" label="Date" type="date" />
    <TextField form={form} name="description" label="Description / memo" />
    {lines.fields.map((line, index) => <div className="posting" key={line.formKey}>
      <h3>Posting {index + 1}</h3>
      <SelectField form={form} name={`postings.${index}.target_type`} label="Account or category" options={options(['account', 'category'])} />
      <SelectField form={form} name={`postings.${index}.target_id`} label="Target" options={form.watch(`postings.${index}.target_type`) === 'account' ? choices.accounts : choices.categories} />
      <SelectField form={form} name={`postings.${index}.side`} label="Side" options={options(['Debit', 'Credit'])} />
      <TextField form={form} name={`postings.${index}.amount`} label="Amount" />
      <SelectField form={form} name={`postings.${index}.payee_id`} label="Payee / customer" options={[blank, ...choices.payees]} />
      <TextField form={form} name={`postings.${index}.description`} label="Description" />
      <button type="button" disabled={lines.fields.length <= 2} onClick={() => lines.remove(index)}>Remove posting {index + 1}</button>
    </div>)}
    <button type="button" onClick={() => lines.append({ id: crypto.randomUUID(), target_type: 'account', target_id: '', side: 'Debit', amount: '0.00', payee_id: '', description: '' })}>Add posting</button>
    <p className="muted">Debits and credits must balance. Saving validates the complete journal.</p>
  </>;
}

function JournalEditor({ row, onClose }: { row: Schemas['Journal']; onClose: () => void }) {
  const session = useEntity();
  return <ProtectedEditor session={session} loaded={journalLoaded(row)} title="Edit journal" onClose={onClose}
    save={async (id, baseline, changes) => journalLoaded(await api.updateJournal(session, id, { baseline, changes }))}
    remove={(id, baseline) => api.deleteJournal(session, id, baseline)}
    loadLatest={async id => journalLoaded(await latest(api.journals, session, id))}
    fields={form => <JournalFields form={form} />} />;
}

function mileageLoaded(row: Schemas['Mileage']) {
  const values: Schemas['MileageChanges'] = { trip_date: row.trip_date, miles: row.miles, vehicle: row.vehicle,
    start_location: row.start_location, destination: row.destination, business_purpose: row.business_purpose,
    notes: row.notes, tag_ids: row.tag_ids, new_tag_name: '' };
  return { values, metadata: metadata(row) };
}

function MileageFields({ form }: { form: UseFormReturn<Schemas['MileageChanges']> }) {
  const session = useEntity();
  const choices = useReferenceChoices(session);
  if (choices.pending) return <LoadingState label="Loading choices…" />;
  if (choices.error) return <ErrorNotice error={choices.error} />;
  return <><TextField form={form} name="trip_date" label="Trip date" type="date" />
    <TextField form={form} name="vehicle" label="Vehicle" />
    <TextField form={form} name="miles" label="Business miles" />
    <SelectField form={form} name="tag_ids" label="Tags" options={choices.tags} multiple />
    <TextField form={form} name="new_tag_name" label="New tag name (optional)" />
    <TextField form={form} name="start_location" label="Starting location" />
    <TextField form={form} name="destination" label="Destination" />
    <TextField form={form} name="business_purpose" label="Business purpose" />
    <TextField form={form} name="notes" label="Notes" /></>;
}

function MileageEditor({ row, onClose }: { row: Schemas['Mileage']; onClose: () => void }) {
  const session = useEntity();
  return <ProtectedEditor session={session} loaded={mileageLoaded(row)} title="Edit mileage trip" onClose={onClose}
    save={async (id, baseline, changes) => mileageLoaded(await api.updateMileage(session, id, { baseline, changes }))}
    remove={(id, baseline) => api.deleteMileage(session, id, baseline)}
    loadLatest={async id => mileageLoaded(await latest(api.mileage, session, id))}
    fields={form => <MileageFields form={form} />} />;
}

export function BookkeepingPage({ resource }: { resource: 'transactions' | 'journals' | 'mileage' }) {
  const title = resource[0].toUpperCase() + resource.slice(1);
  return <><h1>{title}</h1><p className="lead">Review existing records and save changes for this business.</p>
    {resource !== 'mileage' && <nav aria-label="Entries"><Link to="/transactions">Transactions</Link> · <Link to="/journals">Journals</Link></nav>}
    {resource === 'transactions' ? <RecordList key={resource} resource={resource} title="Transactions" list={api.transactions}
      label={row => `${row.txn_date} · ${row.description || row.kind} · ${row.amount}`} canEdit={row => !row.source_type}
      editor={(row, close) => <TransactionEditor row={row} onClose={close} />} />
      : resource === 'journals' ? <RecordList key={resource} resource={resource} title="Journals" list={api.journals}
        label={row => `${row.txn_date} · ${row.description || 'Journal'}`} editor={(row, close) => <JournalEditor row={row} onClose={close} />} />
      : <RecordList key={resource} resource={resource} title="Mileage trips" list={api.mileage}
        label={row => `${row.trip_date} · ${row.destination} · ${row.miles} miles`} editor={(row, close) => <MileageEditor row={row} onClose={close} />} />}
  </>;
}
