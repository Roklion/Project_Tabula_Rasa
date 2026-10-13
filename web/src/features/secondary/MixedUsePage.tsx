import { PageHeader } from '../../components/VisualPrimitives';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useWatch, type UseFormReturn } from 'react-hook-form';
import { api, type Schemas } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { ErrorNotice, LoadingState } from '../../components/States';
import { localDate } from '../../components/localDate';
import { TextField } from '../concurrency/Fields';
import { ProtectedEditor } from '../concurrency/ProtectedEditor';
import { RecordList } from '../concurrency/RecordList';
import { SavedFields } from '../concurrency/SavedFields';
import { useLoadedRecord } from '../concurrency/useLoadedRecord';
import { CreateEditor } from '../workflows/CreateEditor';
import { ExpenseReferences } from './ExpenseReferences';

type Draft = Schemas['MixedUseChanges'];
const initial = (): Draft => ({ txn_date: localDate(), total_expense: '', business_use_percentage: '100', allocation_rationale: '',
  account_id: '', category_id: '', payee_id: '', tag_ids: [], description: '', reference: '', new_payee_name: '', new_tag_name: '' });
const loaded = (row: Schemas['MixedUse']): { metadata: { id: string; baseline: string }; values: Draft } => ({ metadata: { id: row.id, baseline: row.baseline }, values: {
  txn_date: row.txn_date, total_expense: row.total_expense, business_use_percentage: row.business_use_percentage, allocation_rationale: row.allocation_rationale,
  account_id: row.account_id, category_id: row.category_id, payee_id: row.payee_id, tag_ids: row.tag_ids,
  description: row.description, reference: row.reference, new_payee_name: '', new_tag_name: '',
} satisfies Draft });

function MixedFields({ form, creating = false }: { form: UseFormReturn<Draft>; creating?: boolean }) {
  const session = useEntity();
  const [total, percentage] = useWatch({ control: form.control, name: ['total_expense', 'business_use_percentage'] });
  const valid = /^\d+(\.\d+)?$/.test(total) && /^\d+(\.\d+)?$/.test(percentage);
  const preview = useQuery({ queryKey: [...resourceKey(session, 'mixed-use'), 'allocation', total, percentage],
    queryFn: ({ signal }) => api.previewAllocation(session, { total_expense: total, business_use_percentage: percentage }, signal), enabled: valid, retry: false });
  return <><TextField form={form} name="txn_date" label="Date" type="date" />
    <TextField form={form} name="total_expense" label="Total expense" />
    <TextField form={form} name="business_use_percentage" label="Business use %" />
    <TextField form={form} name="allocation_rationale" label="Allocation rationale" />
    <p role="status">Ledger result: {valid && preview.data ? preview.data.allocated_amount : 'Enter valid allocation inputs.'}</p>
    {valid && preview.isFetching && <LoadingState label="Calculating allocation…" />}
    {valid && preview.isError && <ErrorNotice error={preview.error} />}
    <ExpenseReferences form={form} creating={creating} inline />
  </>;
}

export function MixedUsePage() {
  const session = useEntity();
  return <><PageHeader title="Mixed-use expenses" description="Manage the authoritative source; the ledger receives only its business allocation."
    actions={session.capabilities.includes('bookkeeping:write') && <Link className="button" to="/mixed-use/new">Add mixed-use expense</Link>} />
    <RecordList resource="mixed-use" title="Mixed-use Expense Log" list={api.mixedUse} label={row => row.txn_date + ' · ' + (row.description || row.id)}
      canEdit={() => false} editor={() => null} detailsTarget={row => row.ledger_status === 'linked' ? '/mixed-use/' + encodeURIComponent(row.id) : undefined}
      columns={[{ title: 'Total', render: row => row.total_expense }, { title: 'Business %', render: row => row.business_use_percentage },
        { title: 'Allocated', render: row => row.allocated_amount }, { title: 'Rationale', render: row => row.allocation_rationale },
        { title: 'Relationship', render: row => row.ledger_status === 'linked' ? 'Linked · ' + row.linked_transaction_id : 'Inspection required; editing unavailable' },
        { title: 'Schedule', render: row => row.recurring_schedule_id || 'None' }]} />
  </>;
}

export function NewMixedUse() {
  const session = useEntity(); const navigate = useNavigate();
  return <><h1>Add mixed-use expense</h1>{session.capabilities.includes('bookkeeping:write') ?
    <CreateEditor initial={initial} title="Save mixed-use expense" fields={form => <MixedFields form={form} creating />}
      create={(values, id) => api.createMixedUse(session, { ...values, source_id: id, linked_transaction_id: id + ':projection' })}
      onClose={() => navigate('/mixed-use')} /> : <p>Read-only access.</p>}</>;
}

export function MixedUseDetail() {
  const { recordId = '' } = useParams();
  return <MixedUseDetailQuery key={recordId} recordId={recordId} />;
}

function MixedUseDetailQuery({ recordId }: { recordId: string }) {
  const session = useEntity(); const navigate = useNavigate();
  const query = useLoadedRecord(session, 'mixed-use', recordId, api.mixedUseSource);
  if (query.initializing) return <><h1>Mixed-use expense</h1><LoadingState /></>;
  if (!query.initialized || !query.data) return <><h1>Mixed-use expense</h1><ErrorNotice error={query.error} onReview={() => void query.refetch()} /></>;
  const data = query.data;
  return <><h1>Mixed-use expense</h1>{<>
    <p>Source {data.id} · Projection {data.linked_transaction_id} · Allocated {data.allocated_amount}</p>
    <Link to={'/mixed-use/' + encodeURIComponent(data.id) + '/receipts'}>Manage source receipts</Link>
    {data.recurring_schedule_id && <p>Schedule {data.recurring_schedule_id} · {data.recurring_scheduled_date} · {data.recurring_occurrence_type}</p>}
    {session.capabilities.includes('bookkeeping:write') ? <ProtectedEditor key={recordId} session={session} loaded={loaded(data)} title="Edit mixed-use expense"
      fields={form => <MixedFields form={form} />} onClose={() => navigate('/mixed-use')}
      save={async (id, baseline, changes) => loaded(await api.updateMixedUse(session, id, { baseline, changes }))}
      remove={async (id, baseline) => { await api.deleteMixedUse(session, id, baseline); navigate('/mixed-use'); }} loadLatest={async id => loaded(await api.mixedUseSource(session, id))} />
      : <SavedFields title="Saved mixed-use expense" values={loaded(data).values} fields={form => <>
        <TextField form={form} name="txn_date" label="Date" type="date" />
        <TextField form={form} name="total_expense" label="Total expense" />
        <TextField form={form} name="business_use_percentage" label="Business use %" />
        <TextField form={form} name="allocation_rationale" label="Allocation rationale" />
        <ExpenseReferences form={form} />
      </>} />}
  </>}</>;
}
