import { useState } from 'react';
import { api, ApiError, type Schemas } from '../../api/client';
import { useEntity } from '../../app/context';
import { useLoadedForm } from '../../components/useLoadedForm';
import { ErrorNotice, SuccessNotice } from '../../components/States';
import { UnsavedChanges } from '../../components/UnsavedChanges';
import { ReloadPrompt } from './ProtectedEditor';
import { useProtectedMutation } from './mutations';
import { ActionButton, FormSection, SectionHeader } from '../../components/VisualPrimitives';
import { SelectField } from './Fields';

export function ManagedMergeForm({ resource }: { resource: 'payees' | 'tags' }) {
  const session = useEntity();
  const [rows, setRows] = useState<Schemas['ManagedReference'][]>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(false);
  async function open() {
    setLoading(true); setError(undefined);
    try { setRows((await (resource === 'payees' ? api.payees : api.tags)(session)).items); }
    catch (failure) { setError(failure); }
    finally { setLoading(false); }
  }
  if (!session.capabilities.includes('bookkeeping:write')) return <p className="notice neutral">Read-only access. Merging records requires bookkeeping write access.</p>;
  return rows ? <MergeEditor resource={resource} rows={rows} onClose={() => setRows(undefined)} />
    : <section className="surface"><SectionHeader title="Choose records to merge" description="Keep one active record and move the selected source references into it." />
      <div className="actions"><ActionButton tone="primary" pending={loading} onClick={() => void open()}>Merge {resource}</ActionButton></div>
      {error !== undefined && <ErrorNotice error={error} operation="read" onReview={() => void open()} />}</section>;
}

function loaded(rows: Schemas['ManagedReference'][]) {
  return { values: { target: '', sources: [] as string[] }, metadata: {
    rows: structuredClone(rows), baselines: Object.fromEntries(rows.map(row => [row.id, row.baseline])),
  } };
}

function MergeEditor({ resource, rows, onClose }: { resource: 'payees' | 'tags'; rows: Schemas['ManagedReference'][]; onClose: () => void }) {
  const session = useEntity();
  const { form, metadata, reload } = useLoadedForm(loaded(rows));
  const [review, setReview] = useState(false);
  const [error, setError] = useState<unknown>();
  const [success, setSuccess] = useState(false);
  const [reloading, setReloading] = useState(false);
  const merge = resource === 'payees' ? api.mergePayees : api.mergeTags;
  const list = resource === 'payees' ? api.payees : api.tags;
  const mutation = useProtectedMutation(session, async (values: { target: string; sources: string[] }) => {
    if (!values.target || !values.sources.length || values.sources.includes(values.target)) throw new ApiError('validation');
    const baselines = Object.fromEntries([values.target, ...values.sources].map(id => [id, metadata.baselines[id]]));
    if (Object.values(baselines).some(token => !token)) throw new ApiError('baseline_required');
    await merge(session, values.target, { source_ids: values.sources, baselines });
    form.reset(); setSuccess(true);
  });
  async function reloadLatest() {
    setReloading(true);
    try { reload(loaded((await list(session)).items)); setReview(false); setError(undefined); }
    catch (failure) { setReview(false); setError(failure); }
    finally { setReloading(false); }
  }
  const target = form.watch('target');
  const pending = mutation.isPending || reloading;
  return <section className="surface editor" aria-label={'Merge ' + resource}><SectionHeader title={'Merge ' + resource} /><UnsavedChanges dirty={form.formState.isDirty} />
    {success ? <><SuccessNotice>Records merged.</SuccessNotice><div className="actions"><ActionButton onClick={onClose}>Back to records</ActionButton></div></>
      : <form onSubmit={form.handleSubmit(async values => { setError(undefined); try { await mutation.mutateAsync(values); } catch (failure) { setError(failure); } })}>
        {error !== undefined && <ErrorNotice error={error} onReview={() => setReview(true)} />}
        {review && <ReloadPrompt pending={pending} onKeep={() => setReview(false)} onReload={() => void reloadLatest()} />}
        <fieldset disabled={pending || review}><FormSection title="Keep one record">
          <SelectField form={form} name="target" label="Keep this record" options={[{ id: '', name: 'Choose target' }, ...metadata.rows.filter(row => row.active)]}
            onChange={() => form.setValue('sources', form.getValues('sources').filter(id => id !== form.getValues('target')), { shouldDirty: true })} />
        </FormSection><FormSection title="Source records" description="Merge these records into the selected target:">
          <div className="mergeSources formSpan">{metadata.rows.filter(row => row.id !== target).map(row => <label className="checkbox" key={row.id}><input type="checkbox" value={row.id} {...form.register('sources')} />
            <span>{row.name}{!row.active && ' (inactive)'}</span></label>)}</div>
        </FormSection></fieldset><p className="fieldHint">The selected source records will be removed and their references moved to the target.</p>
        <div className="actions formActions"><ActionButton tone="primary" type="submit" pending={mutation.isPending} disabled={pending || review}>Confirm merge</ActionButton></div>
      </form>}
  </section>;
}
