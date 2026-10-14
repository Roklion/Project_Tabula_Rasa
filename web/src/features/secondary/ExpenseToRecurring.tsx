import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, type Schemas, type Session } from '../../api/client';
import { useEntity } from '../../app/context';
import { ErrorNotice, LoadingState, SuccessNotice } from '../../components/States';
import { TextField } from '../concurrency/Fields';
import { ProtectedEditor } from '../concurrency/ProtectedEditor';
import { latest } from '../concurrency/mutations';
import { useLoadedRecord } from '../concurrency/useLoadedRecord';
import { ExpenseReferences } from './ExpenseReferences';
import { RecurrenceFields } from './RecurringPage';

type Draft = Schemas['OrdinaryExpenseChanges'] & { name: string; recurrence_unit: string; recurrence_interval: string; end_date: string };
const read = (session: Session, id: string) => latest(api.transactions, session, id);
const loaded = (row: Schemas['Transaction']) => ({ metadata: { id: row.id, baseline: row.baseline }, values: {
  txn_date: row.txn_date, amount: row.amount, account_id: row.account_id, category_id: row.category_id,
  payee_id: row.payee_id, tag_ids: row.tag_ids, description: row.description, reference: row.reference,
  new_payee_name: '', new_tag_name: '', name: row.description || 'Recurring expense', recurrence_unit: 'month', recurrence_interval: '1', end_date: '',
} satisfies Draft });

export function ExpenseToRecurring() {
  const { recordId = '' } = useParams();
  return <ExpenseToRecurringQuery key={recordId} recordId={recordId} />;
}

function ExpenseToRecurringQuery({ recordId }: { recordId: string }) {
  const session = useEntity(); const navigate = useNavigate();
  const [scheduleId] = useState(() => crypto.randomUUID());
  const [completed, setCompleted] = useState<Schemas['RecurringDetail']>();
  const [original, setOriginal] = useState<Schemas['Transaction']>();
  const query = useLoadedRecord(session, 'transactions', recordId, read);
  if (!original && query.initialized && query.data) setOriginal(structuredClone(query.data));
  if (query.initializing) return <><h1>Make expense recurring</h1><LoadingState /></>;
  if (!query.initialized || !query.data) return <><h1>Make expense recurring</h1><ErrorNotice error={query.error} onReview={() => void query.refetch()} /></>;
  const row = original ?? query.data;
  return <><h1>Make expense recurring</h1>
    {completed ? <><SuccessNotice>Expense made recurring.</SuccessNotice><p>The saved expense is the initial occurrence. Receipts stay with this occurrence.</p>
      <Link to={'/recurring/' + encodeURIComponent(completed.schedule.id)}>View recurring schedule</Link></> :
      !session.capabilities.includes('bookkeeping:write') ? <p>Read-only access.</p> :
        row.kind !== 'Expense' || row.source_type || row.recurring_schedule_id ? <p>This record cannot be converted. Choose an ordinary Expense without a recurring schedule.</p> : <>
          <p>The saved edit becomes this schedule's initial occurrence. Future occurrences use the template without receipts.</p>
          <ProtectedEditor<Draft> session={session} loaded={loaded(row)} title="Make expense recurring" onClose={() => navigate('/transactions')}
            uncertainGuidance={<p>The schedule may already exist. Inspect <Link to="/recurring">Recurring expenses</Link> before retrying this preserved conversion draft or starting another conversion.</p>}
            confirmSave={() => true} saveConfirmation={{ title: 'Make expense recurring', confirmLabel: 'Confirm recurring conversion',
              description: 'Save this expense and create its recurring schedule?' }}
            fields={form => <><TextField form={form} name="txn_date" label="Date" type="date" />
              <TextField form={form} name="amount" label="Amount" /><ExpenseReferences form={form} inline />
              <TextField form={form} name="name" label="Schedule name" /><RecurrenceFields form={form} /></>}
            loadLatest={async id => loaded(await read(session, id))}
            save={async (id, baseline, values) => {
              const { name, recurrence_unit, recurrence_interval, end_date, ...changes } = values;
              const result = await api.convertExpenseToRecurring(session, id, { baseline, schedule_id: scheduleId,
                name, recurrence_unit, recurrence_interval, end_date, changes });
              setCompleted(result);
              return { metadata: { id, baseline }, values };
            }} />
        </>}
  </>;
}
