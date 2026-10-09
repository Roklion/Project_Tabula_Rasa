import { useNavigate } from 'react-router-dom';
import { api, type Schemas } from '../../api/client';
import { useEntity } from '../../app/context';
import { TransactionFields, JournalFields } from '../concurrency/BookkeepingEditors';
import { useReferenceChoices } from '../concurrency/useReferenceChoices';
import { CreateEditor } from './CreateEditor';
import { journalTotals } from './journalDraft';

const today = () => {
  const value = new Date();
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
};

export function EntryCreator({ resource }: { resource: 'transactions' | 'journals' }) {
  const session = useEntity();
  const choices = useReferenceChoices(session);
  const navigate = useNavigate();
  const close = () => navigate('/' + resource);
  if (!session.capabilities.includes('bookkeeping:write')) return <p role="alert">This business is read-only.</p>;
  if (resource === 'transactions') return <CreateEditor<Schemas['TransactionChanges']> title="Save transaction" onClose={close}
    initial={() => ({ txn_date: today(), kind: 'Expense', amount: '', account_id: '', to_account_id: '', category_id: '',
      payee_id: '', tag_ids: [], description: '', reference: '', new_payee_name: '', new_tag_name: '' })}
    canSubmit={values => !choices.pending && !choices.error && Boolean(values.account_id) &&
      choices.accounts.some(row => row.id === values.account_id && row.active) &&
      (values.kind === 'Transfer' ? choices.accounts.filter(row => row.active).length >= 2 && Boolean(values.to_account_id)
        : Boolean(values.category_id) && choices.categories.some(row => row.id === values.category_id && row.kind === values.kind))}
    create={(values, transaction_id) => api.createTransaction(session, { ...values, transaction_id,
      to_account_id: values.kind === 'Transfer' ? values.to_account_id : '', category_id: values.kind === 'Transfer' ? '' : values.category_id })}
    fields={form => <TransactionFields form={form} creating />} />;
  return <CreateEditor<Schemas['JournalChanges']> title="Save journal" onClose={close}
    initial={() => ({ txn_date: today(), description: '', postings: ['Debit', 'Credit'].map(side => ({
      id: crypto.randomUUID(), target_type: 'account', target_id: '', side, amount: '', payee_id: '', description: '' })) })}
    canSubmit={values => !choices.pending && !choices.error && journalTotals(values.postings).balanced}
    create={(values, entry_id) => api.createJournal(session, { ...values, entry_id })}
    fields={form => <JournalFields form={form} creating />} />;
}
