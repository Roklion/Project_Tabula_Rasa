import { useState } from 'react';
import { api, ApiError, type Schemas } from '../../api/client';
import { useEntity } from '../../app/context';
import { useLoadedForm } from '../../components/useLoadedForm';
import { ErrorNotice, SuccessNotice } from '../../components/States';
import { UnsavedChanges } from '../../components/UnsavedChanges';
import { ReloadPrompt } from './ProtectedEditor';
import { useProtectedMutation } from './mutations';

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
  if (!session.capabilities.includes('bookkeeping:write')) return null;
  return rows ? <MergeEditor resource={resource} rows={rows} onClose={() => setRows(undefined)} />
    : <div className="actions"><button type="button" disabled={loading} onClick={() => void open()}>Merge {resource}</button>
      {error !== undefined && <ErrorNotice error={error} onReview={() => void open()} />}</div>;
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
    catch (failure) { setError(failure); }
    finally { setReloading(false); }
  }
  const target = form.watch('target');
  const pending = mutation.isPending || reloading;
  return <section className="surface editor"><h2>Merge {resource}</h2><UnsavedChanges dirty={form.formState.isDirty} />
    {success ? <><SuccessNotice>Records merged.</SuccessNotice><button type="button" onClick={onClose}>Back to records</button></>
      : <form onSubmit={form.handleSubmit(async values => { setError(undefined); try { await mutation.mutateAsync(values); } catch (failure) { setError(failure); } })}>
        {error !== undefined && <ErrorNotice error={error} onReview={() => setReview(true)} />}
        {review && <ReloadPrompt pending={pending} onKeep={() => setReview(false)} onReload={() => void reloadLatest()} />}
        <fieldset disabled={pending || review}><label htmlFor="merge-target">Keep this record</label>
          <select id="merge-target" {...form.register('target', { onChange: () => {
            form.setValue('sources', form.getValues('sources').filter(id => id !== form.getValues('target')), { shouldDirty: true });
          } })}><option value="">Choose target</option>
            {metadata.rows.filter(row => row.active).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
          </select><p>Merge these records into the selected target:</p>
          {metadata.rows.filter(row => row.id !== target).map(row => <label className="checkbox" key={row.id}><input type="checkbox" value={row.id} {...form.register('sources')} />{row.name}</label>)}
        </fieldset><p>The selected source records will be removed and their references moved to the target.</p>
        <button type="submit" disabled={pending || review}>Confirm merge</button>
      </form>}
  </section>;
}
