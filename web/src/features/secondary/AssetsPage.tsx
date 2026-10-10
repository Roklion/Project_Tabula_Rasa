import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import type { UseFormReturn } from 'react-hook-form';
import { api, type Schemas } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { ErrorNotice, Field, LoadingState } from '../../components/States';
import { localDate } from '../../components/localDate';
import { SelectField, TextField } from '../concurrency/Fields';
import { ProtectedEditor, type EditorCommand } from '../concurrency/ProtectedEditor';
import { RecordList } from '../concurrency/RecordList';
import { SavedFields } from '../concurrency/SavedFields';
import { useLoadedRecord } from '../concurrency/useLoadedRecord';
import { activeChoices, useReferenceChoices } from '../concurrency/useReferenceChoices';
import { CreateEditor } from '../workflows/CreateEditor';

type Draft = Schemas['AssetChanges'];
const initial = (): Draft => ({ name: '', asset_type: '', notes: '', acquisition_date: localDate(), depreciation_start_date: localDate(),
  cost_basis: '', salvage_value: '0.00', useful_life_quarters: '4', depreciation_expense_account_id: '', accumulated_depreciation_account_id: '',
  payee_id: '', tag_ids: [], reference: '', source_transaction_id: '', status: 'active', retired_date: '' });
const loaded = (row: Schemas['Asset']): { metadata: { id: string; baseline: string }; values: Draft } => ({ metadata: { id: row.id, baseline: row.baseline }, values: {
  name: row.name, asset_type: row.asset_type, notes: row.notes, acquisition_date: row.acquisition_date, depreciation_start_date: row.depreciation_start_date,
  cost_basis: row.cost_basis, salvage_value: row.salvage_value, useful_life_quarters: row.useful_life_quarters,
  depreciation_expense_account_id: row.depreciation_expense_account_id, accumulated_depreciation_account_id: row.accumulated_depreciation_account_id,
  payee_id: row.payee_id, tag_ids: row.tag_ids, reference: row.reference, source_transaction_id: row.source_transaction_id, status: row.status, retired_date: row.retired_date,
} satisfies Draft });

function AssetFields({ form, creating = false, termsLocked = false, accountsLocked = false }: {
  form: UseFormReturn<Draft>; creating?: boolean; termsLocked?: boolean; accountsLocked?: boolean;
}) {
  const session = useEntity(); const choices = useReferenceChoices(session);
  const types = useQuery({ queryKey: [...resourceKey(session, 'assets'), 'types'], queryFn: ({ signal }) => api.assetTypes(session, signal) });
  const original = creating ? undefined : form.formState.defaultValues;
  const none = { id: '', name: 'None' };
  if (choices.pending || types.isPending) return <LoadingState label="Loading asset choices…" />;
  if (choices.error || types.isError) return <ErrorNotice error={choices.error || types.error} />;
  return <><TextField form={form} name="name" label="Asset name" />
    <SelectField form={form} name="asset_type" label="Asset type" options={[none, ...types.data.items.map(name => ({ id: name, name }))]} />
    <TextField form={form} name="notes" label="Notes" />
    <TextField form={form} name="acquisition_date" label="Acquisition date" type="date" />
    <fieldset disabled={termsLocked}><legend>Depreciation terms{termsLocked ? ' (locked by saved history)' : ''}</legend>
      <TextField form={form} name="depreciation_start_date" label="Depreciation starts" type="date" />
      <TextField form={form} name="cost_basis" label="Cost basis" />
      <TextField form={form} name="salvage_value" label="Salvage value" />
      <TextField form={form} name="useful_life_quarters" label="Useful life (quarters)" />
    </fieldset>
    <fieldset disabled={accountsLocked}><legend>Posting accounts{accountsLocked ? ' (locked after posting)' : ''}</legend>
      <SelectField form={form} name="depreciation_expense_account_id" label="Depreciation expense category" options={[none, ...choices.categories.filter(row => row.kind === 'Expense')]} />
      <SelectField form={form} name="accumulated_depreciation_account_id" label="Accumulated depreciation account"
        options={[none, ...activeChoices(choices.accounts, [original?.accumulated_depreciation_account_id]).filter(row => row.type === 'Other' && row.classification === 'Asset')]} />
    </fieldset>
    <SelectField form={form} name="payee_id" label="Payee" options={[none, ...activeChoices(choices.payees, [original?.payee_id])]} />
    <SelectField form={form} name="tag_ids" label="Tags" multiple options={activeChoices(choices.tags, original?.tag_ids ?? [])} />
    <TextField form={form} name="reference" label="Reference" />
    <TextField form={form} name="source_transaction_id" label="Acquisition transaction ID (optional)" />
    {!creating && <><SelectField form={form} name="status" label="Asset status" options={['active', 'retired'].map(id => ({ id, name: id }))} />
      <TextField form={form} name="retired_date" label="Retirement date" type="date" /></>}
  </>;
}

export function AssetsPage() {
  const session = useEntity();
  return <><h1>Assets</h1><p className="lead">Business-use fixed assets and quarterly straight-line depreciation.</p>
    {session.capabilities.includes('bookkeeping:write') && <Link className="button" to="/assets/new">Add asset</Link>}
    <RecordList resource="assets" title="Asset register" list={api.assets} label={row => row.name} canEdit={() => false} editor={() => null}
      detailsTarget={row => '/assets/' + encodeURIComponent(row.id)} columns={[{ title: 'Type', render: row => row.asset_type },
        { title: 'Status', render: row => row.status }, { title: 'Cost basis', render: row => row.cost_basis }, { title: 'Salvage', render: row => row.salvage_value },
        { title: 'Life (quarters)', render: row => row.useful_life_quarters }, { title: 'ID', render: row => row.id }]} />
  </>;
}

export function NewAsset() {
  const session = useEntity(); const navigate = useNavigate();
  return <><h1>Add asset</h1>{session.capabilities.includes('bookkeeping:write') ? <CreateEditor title="Save asset" initial={initial}
    fields={form => <AssetFields form={form} creating />} create={(values, id) => {
      const fields: Omit<Draft, 'status' | 'retired_date'> & Partial<Pick<Draft, 'status' | 'retired_date'>> = { ...values };
      delete fields.status; delete fields.retired_date;
      return api.createAsset(session, { ...fields, asset_id: id });
    }} onClose={() => navigate('/assets')} /> : <p>Read-only access.</p>}</>;
}

function AssetEditor({ detail }: { detail: Schemas['AssetDetail'] }) {
  const session = useEntity(); const navigate = useNavigate();
  const [through, setThrough] = useState(localDate); const [sequence, setSequence] = useState('1');
  const [amount, setAmount] = useState(''); const [reason, setReason] = useState('');
  const commands: EditorCommand[] = [{ label: 'Post due depreciation', description: 'Post pending quarters through ' + through + '. Posted accounting facts and terms become immutable.',
    run: async (id, baseline) => { const result = await api.postDepreciation(session, id, { baseline, through_date: through }); return 'Posted ' + result.posted_count + ' depreciation period(s).'; } }];
  if (!detail.posting_accounts_locked) commands.push(
    { label: 'Save period override', description: 'Save an amount override with its reason for quarter ' + sequence + '.',
      run: async (id, baseline) => { await api.overrideDepreciation(session, id, Number(sequence), { baseline, amount, reason, as_of_date: localDate() }); return 'Period override saved.'; } },
    { label: 'Remove period override', description: 'Remove the saved override for quarter ' + sequence + '.',
      run: async (id, baseline) => { await api.removeDepreciationOverride(session, id, Number(sequence), baseline); return 'Period override removed.'; } },
  );
  return <ProtectedEditor session={session} loaded={loaded(detail.asset)} title="Edit asset"
    fields={form => <AssetFields form={form} termsLocked={detail.terms_locked} accountsLocked={detail.posting_accounts_locked} />}
    confirmSave={(values, defaults) => values.status === 'retired' && defaults.status !== 'retired'}
    saveConfirmation={{ title: 'Retire asset', confirmLabel: 'Confirm retirement', description: 'Retire this asset and save your changes? Existing posted facts are retained.' }}
    save={async (id, baseline, changes) => loaded(await api.updateAsset(session, id, { baseline, changes }))}
    remove={detail.can_delete ? async (id, baseline) => { await api.deleteAsset(session, id, baseline); navigate('/assets'); } : undefined}
    loadLatest={async id => loaded((await api.asset(session, id)).asset)} onClose={() => navigate('/assets')} commands={commands}
    commandFields={<><Field id="asset-through" label="Post depreciation through"><input id="asset-through" type="date" value={through} onChange={event => setThrough(event.target.value)} /></Field>
      {!detail.posting_accounts_locked && <><Field id="override-sequence" label="Override quarter"><select id="override-sequence" value={sequence} onChange={event => setSequence(event.target.value)}>
        {detail.schedule.map(period => <option key={period.sequence} value={period.sequence}>{period.sequence} · {period.scheduled_date}</option>)}</select></Field>
        <Field id="override-amount" label="Override amount"><input id="override-amount" value={amount} onChange={event => setAmount(event.target.value)} /></Field>
        <Field id="override-reason" label="Override reason"><input id="override-reason" value={reason} onChange={event => setReason(event.target.value)} /></Field></>}
    </>} />;
}

export function AssetDetail() {
  const { recordId = '' } = useParams();
  return <AssetDetailQuery key={recordId} recordId={recordId} />;
}

function AssetDetailQuery({ recordId }: { recordId: string }) {
  const session = useEntity();
  const query = useLoadedRecord(session, 'assets', recordId, api.asset);
  if (query.initializing) return <><h1>Asset detail</h1><LoadingState /></>;
  if (!query.initialized || !query.data) return <><h1>Asset detail</h1><ErrorNotice error={query.error} onReview={() => void query.refetch()} /></>;
  const data = query.data;
  return <><h1>Asset detail</h1><Link to="/assets">Back to asset register</Link>
    {<>
      <h2>{data.asset.name}</h2><p>{data.asset.asset_type} · {data.asset.status} · {data.asset.depreciation_method}</p>
      <p>Cost basis {data.asset.cost_basis} · Salvage {data.asset.salvage_value} · {data.asset.useful_life_quarters} quarters</p>
      {data.asset.source_transaction_id && <p>Acquisition transaction: {data.asset.source_transaction_id}</p>}
      <div className="tableScroll" role="region" aria-label="Depreciation schedule" tabIndex={0}><table><caption>Depreciation schedule and saved history</caption>
        <thead><tr>{['Quarter', 'Date', 'Amount', 'Cumulative', 'Book value', 'Override reason', 'Posting state', 'Ledger entry ID'].map(name => <th key={name} scope="col">{name}</th>)}</tr></thead>
        <tbody>{data.schedule.map(period => <tr key={period.sequence}><th scope="row">{period.sequence}</th><td>{period.scheduled_date}</td>
          <td>{period.depreciation_amount}</td><td>{period.cumulative_depreciation}</td><td>{period.remaining_book_value}</td><td>{period.override_reason}</td>
          <td>{period.posting_status}</td><td>{period.journal_entry_id}</td></tr>)}</tbody></table></div>
      <p>{data.history.length} posted period(s). {data.can_delete ? 'No saved depreciation history.' : 'Saved history is retained; permanent deletion is unavailable.'}</p>
      {session.capabilities.includes('bookkeeping:write') ? <AssetEditor key={recordId} detail={data} />
        : <SavedFields title="Saved asset terms" values={loaded(data.asset).values} fields={form => <AssetFields form={form} />} />}
    </>}
  </>;
}
