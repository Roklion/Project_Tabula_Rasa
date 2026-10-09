import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import type { Path, UseFormReturn } from 'react-hook-form';
import { api, type Schemas } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { ConfirmationDialog } from '../../components/ConfirmationDialog';
import { ErrorNotice, Field, LoadingState, SuccessNotice } from '../../components/States';
import { localDate } from '../../components/localDate';
import { SelectField, TextField } from '../concurrency/Fields';
import { ProtectedEditor } from '../concurrency/ProtectedEditor';
import { RecordList } from '../concurrency/RecordList';
import { SavedFields } from '../concurrency/SavedFields';
import { useProtectedMutation } from '../concurrency/mutations';
import { CreateEditor } from '../workflows/CreateEditor';
import { ExpenseReferences } from './ExpenseReferences';

type Changes = Schemas['RecurringChanges'];
type Draft = Changes & { start_date: string; source_kind: string };
const initial = (): Draft => ({ name: '', start_date: localDate(), source_kind: 'transaction', recurrence_unit: 'month', recurrence_interval: '1',
  end_date: '', amount: '', total_expense: '', business_use_percentage: '100', allocation_rationale: '', account_id: '', category_id: '', payee_id: '', tag_ids: [], description: '', reference: '' });
const loaded = (row: Schemas['Recurring']) => ({ metadata: { id: row.id, baseline: row.baseline }, values: {
  name: row.name, recurrence_unit: row.recurrence_unit, recurrence_interval: row.recurrence_interval, end_date: row.end_date,
  amount: row.amount, total_expense: row.total_expense, business_use_percentage: row.business_use_percentage, allocation_rationale: row.allocation_rationale,
  account_id: row.account_id, category_id: row.category_id, payee_id: row.payee_id, tag_ids: row.tag_ids, description: row.description, reference: row.reference,
} satisfies Changes });

function RecurringFields<T extends Changes>({ form, creating = false, mixed = false }: { form: UseFormReturn<T>; creating?: boolean; mixed?: boolean }) {
  const path = (name: string) => name as Path<T>;
  return <><TextField form={form} name={path('name')} label="Schedule name" />
    {creating && <><TextField form={form} name={path('start_date')} label="Start date" type="date" />
      <SelectField form={form} name={path('source_kind')} label="Expense source" options={[{ id: 'transaction', name: 'Ordinary expense' }, { id: 'mixed_use', name: 'Mixed-use expense' }]} /></>}
    <SelectField form={form} name={path('recurrence_unit')} label="Repeat unit" options={['day', 'week', 'month', 'year'].map(id => ({ id, name: id }))} />
    <TextField form={form} name={path('recurrence_interval')} label="Repeat every" />
    <TextField form={form} name={path('end_date')} label="End date (optional)" type="date" />
    {(creating ? form.watch(path('source_kind')) === 'mixed_use' : mixed) ? <>
      <TextField form={form} name={path('total_expense')} label="Total expense" />
      <TextField form={form} name={path('business_use_percentage')} label="Business use %" />
      <TextField form={form} name={path('allocation_rationale')} label="Allocation rationale" />
    </> : <TextField form={form} name={path('amount')} label="Amount" />}
    <ExpenseReferences form={form} creating={creating} />
  </>;
}

function GenerateOccurrences() {
  const session = useEntity(); const [through, setThrough] = useState(localDate); const [confirm, setConfirm] = useState(false);
  const [result, setResult] = useState<Schemas['ReconcileResult']>(); const [failure, setFailure] = useState<unknown>();
  const mutation = useProtectedMutation(session, () => api.reconcileRecurring(session, { through_date: through }));
  async function generate() {
    setResult(undefined); setFailure(undefined);
    try { setResult(await mutation.mutateAsync()); } catch (error) { setFailure(error); }
    finally { setConfirm(false); }
  }
  return <section className="surface"><h2>Generate due occurrences</h2>
    <p>Generation runs only after this explicit action. Page visits never run a scheduler.</p>
    <Field id="recurring-through" label="Generate through"><input id="recurring-through" type="date" value={through} disabled={mutation.isPending}
      onChange={event => setThrough(event.target.value)} /></Field>
    <button disabled={mutation.isPending || !through} onClick={event => { event.currentTarget.focus(); setConfirm(true); }}>Generate due occurrences</button>
    {result && <SuccessNotice>Generated {result.generated_count} occurrence(s). {result.attention_count} schedule(s) require attention.</SuccessNotice>}
    {failure !== undefined && <ErrorNotice error={failure} />}
    {confirm && <ConfirmationDialog title="Generate due occurrences" keepLabel="Keep records" confirmLabel="Confirm generation" pending={mutation.isPending}
      onKeep={() => setConfirm(false)} onConfirm={() => void generate()}>Generate due expenses through {through} using the current schedule templates?</ConfirmationDialog>}
  </section>;
}

export function RecurringPage() {
  const session = useEntity();
  return <><h1>Recurring expenses</h1><p className="lead">Templates affect future occurrences. Existing expenses retain their provenance.</p>
    <Link to="/transactions">Back to Transactions</Link>
    {session.capabilities.includes('bookkeeping:write') && <Link className="button" to="/recurring/new">Add recurring expense</Link>}
    <RecordList resource="recurring" title="Recurring schedules" list={api.recurring} label={row => row.name} canEdit={() => false} editor={() => null}
      detailsTarget={row => '/recurring/' + encodeURIComponent(row.id)} columns={[
        { title: 'Cadence', render: row => row.recurrence_interval + ' ' + row.recurrence_unit }, { title: 'Next due', render: row => row.next_due_date || 'None' },
        { title: 'Latest occurrence', render: row => row.latest_current_occurrence_date || 'None' }, { title: 'Status', render: row => row.status },
        { title: 'Attention', render: row => row.attention_message || 'None' }, { title: 'ID', render: row => row.id }]} />
    {session.capabilities.includes('bookkeeping:write') && <GenerateOccurrences />}
  </>;
}

export function NewRecurring() {
  const session = useEntity(); const navigate = useNavigate();
  return <><h1>Add recurring expense</h1><p>Save creates the schedule and its initial occurrence together.</p>
    {session.capabilities.includes('bookkeeping:write') ? <CreateEditor title="Save recurring expense" initial={initial}
      fields={form => <RecurringFields form={form} creating />} create={(values, id) => api.createRecurring(session, { ...values, schedule_id: id })}
      onClose={() => navigate('/recurring')} /> : <p>Read-only access.</p>}</>;
}

export function RecurringDetail() {
  const session = useEntity(); const navigate = useNavigate(); const { recordId = '' } = useParams();
  const query = useQuery({ queryKey: [...resourceKey(session, 'recurring'), recordId], queryFn: ({ signal }) => api.recurringSchedule(session, recordId, signal) });
  if (!query.data) return <><h1>Recurring schedule</h1>{query.isError ? <ErrorNotice error={query.error} onReview={() => void query.refetch()} /> : <LoadingState />}</>;
  const data = query.data;
  return <><h1>Recurring schedule</h1>{<>
    <p>{data.schedule.name} · {data.schedule.status} · {data.schedule.id}</p>
    <p>Starts {data.schedule.start_date} · {data.schedule.source_kind === 'mixed_use' ? 'Mixed-use expense' : 'Ordinary expense'}</p>
    {data.schedule.attention_message && <p role="alert">{data.schedule.attention_message}</p>}
    <div className="tableScroll" role="region" aria-label="Generated occurrences" tabIndex={0}><table><caption>Current occurrences and provenance</caption>
      <thead><tr>{['Date', 'Amount', 'Role', 'Schedule date', 'Source', 'Entry ID'].map(name => <th key={name} scope="col">{name}</th>)}</tr></thead>
      <tbody>{data.occurrences.map(row => <tr key={row.id}><th scope="row">{row.txn_date}</th><td>{row.amount}</td><td>{row.recurring_occurrence_type}</td>
        <td>{row.recurring_scheduled_date}</td><td>{row.source_id || 'Ordinary expense'}</td><td>{row.id}</td></tr>)}</tbody></table></div>
    {session.capabilities.includes('bookkeeping:write') ? <ProtectedEditor key={recordId} session={session} loaded={loaded(data.schedule)} title="Edit recurring schedule"
      fields={form => <RecurringFields form={form} mixed={data.schedule.source_kind === 'mixed_use'} />} onClose={() => navigate('/recurring')}
      save={async (id, baseline, changes) => loaded(await api.updateRecurring(session, id, { baseline, changes }))}
      loadLatest={async id => loaded((await api.recurringSchedule(session, id)).schedule)}
      commands={(data.schedule.status === 'ended' ? [] : [data.schedule.status === 'active' ? 'pause' : 'resume', 'end'] as const).map(transition => ({
        label: transition[0].toUpperCase() + transition.slice(1) + ' schedule', description: transition === 'end' ? 'End future generation permanently; retain this schedule and its occurrences.' : transition === 'pause' ? 'Pause future generation.' : 'Resume future generation.',
        run: async (id, baseline) => { await api.transitionRecurring(session, id, baseline, transition); return 'Schedule ' + transition + ' completed.'; },
      }))} /> : <SavedFields title="Saved recurring schedule" values={loaded(data.schedule).values}
        fields={form => <RecurringFields form={form} mixed={data.schedule.source_kind === 'mixed_use'} />} />}
  </>}</>;
}
