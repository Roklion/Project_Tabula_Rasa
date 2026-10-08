import { useState, type ReactNode } from 'react';
import type { FieldValues, UseFormReturn } from 'react-hook-form';
import { ApiError, type Session } from '../../api/client';
import { useProtectedMutation } from './mutations';
import { useLoadedForm, type LoadedForm } from '../../components/useLoadedForm';
import { ErrorNotice, SuccessNotice } from '../../components/States';
import { UnsavedChanges } from '../../components/UnsavedChanges';

export type LoadMetadata = { id: string; baseline: string };

export function ReloadPrompt({ pending, onKeep, onReload }: { pending: boolean; onKeep: () => void; onReload: () => void }) {
  return <div className="notice warning" role="alertdialog" aria-label="Reload record">
    <p>Reload replaces your draft with the latest saved record. Review it before submitting again.</p>
    <button type="button" disabled={pending} onClick={onKeep}>Keep draft</button>
    <button type="button" disabled={pending} onClick={onReload}>Discard draft and reload</button>
  </div>;
}

export function ProtectedEditor<T extends FieldValues>({ session, loaded, title, fields, save, remove, removeLabel = 'Delete', confirmSave, loadLatest, onClose }: {
  session: Session; loaded: LoadedForm<T, LoadMetadata>; title: string;
  fields: (form: UseFormReturn<T>) => ReactNode;
  save: (id: string, baseline: string, changes: T) => Promise<LoadedForm<T, LoadMetadata>>;
  remove: (id: string, baseline: string) => Promise<unknown>;
  confirmSave?: (values: T, defaults: Partial<T>) => boolean;
  removeLabel?: string; loadLatest: (id: string) => Promise<LoadedForm<T, LoadMetadata>>;
  onClose?: () => void;
}) {
  const { form, metadata, reload } = useLoadedForm(loaded);
  const [review, setReview] = useState(false);
  const [pendingSave, setPendingSave] = useState<T>();
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [failure, setFailure] = useState<unknown>();
  const [success, setSuccess] = useState('');
  const [removed, setRemoved] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [closing, setClosing] = useState(false);
  const mutation = useProtectedMutation(session, async (command: { action: 'save' | 'remove'; values?: T }) => {
    if (!metadata.baseline) throw new ApiError('baseline_required');
    if (command.action === 'remove') {
      await remove(metadata.id, metadata.baseline);
      setRemoved(true);
      form.reset(form.getValues());
      setSuccess(removeLabel === 'Deactivate' ? 'Account deactivated.' : 'Record deleted.');
    } else {
      const next = await save(metadata.id, metadata.baseline, command.values!);
      reload(next);
      setSuccess('Changes saved.');
    }
    setConfirmRemove(false); setPendingSave(undefined);
  });
  async function submit(action: 'save' | 'remove', values?: T) {
    setFailure(undefined); setSuccess('');
    try { await mutation.mutateAsync({ action, values }); }
    catch (error) { setFailure(error); }
  }
  async function reloadLatest() {
    setReloading(true); setSuccess('');
    try {
      const next = await loadLatest(metadata.id);
      reload(next); setFailure(undefined); setReview(false); setConfirmRemove(false); setPendingSave(undefined);
    } catch (error) { setFailure(error); }
    finally { setReloading(false); }
  }
  const pending = mutation.isPending || reloading;
  return <section className="surface editor" aria-label={title}>
    <h2>{title}</h2><UnsavedChanges dirty={form.formState.isDirty} />
    {success && <SuccessNotice>{success}</SuccessNotice>}
    {onClose && <button type="button" disabled={pending} onClick={() => form.formState.isDirty ? setClosing(true) : onClose()}>Back to records</button>}
    {closing && <div role="alertdialog" aria-label="Discard draft" className="notice warning">
      <p>Discard your unsaved changes?</p><button type="button" onClick={() => setClosing(false)}>Keep editing</button>
      <button type="button" onClick={() => { form.reset(form.getValues()); onClose?.(); }}>Discard draft and close</button>
    </div>}
    {failure !== undefined && <ErrorNotice error={failure} onReview={() => setReview(true)} />}
    {review && <ReloadPrompt pending={pending} onKeep={() => setReview(false)} onReload={() => void reloadLatest()} />}
    {!removed && <form onSubmit={form.handleSubmit(values => {
      if (confirmSave?.(values, form.formState.defaultValues as Partial<T>)) setPendingSave(values);
      else void submit('save', values);
    })}>
      <fieldset disabled={pending || review || pendingSave !== undefined}>{fields(form)}</fieldset>
      <div className="actions"><button type="submit" disabled={pending || review || pendingSave !== undefined}>Save changes</button>
        <button type="button" disabled={pending || review || pendingSave !== undefined} onClick={() => setConfirmRemove(true)}>{removeLabel}</button></div>
      {pendingSave !== undefined && <div role="alertdialog" aria-label="Deactivate record" className="notice warning">
        <p>Deactivate this record and save your changes? The saved record must still match the one you loaded.</p>
        <button type="button" disabled={pending || review} onClick={() => setPendingSave(undefined)}>Keep editing</button>
        <button type="button" disabled={pending || review} onClick={() => void submit('save', pendingSave)}>Confirm deactivate</button>
      </div>}
      {confirmRemove && <div role="alertdialog" aria-label={removeLabel + ' record'} className="notice warning">
        <p>{removeLabel === 'Delete' ? 'Permanently delete this record?' : 'Deactivate this account?'} The saved record must still match the one you loaded.</p>
        <button type="button" disabled={pending || review} onClick={() => setConfirmRemove(false)}>Keep record</button>
        <button type="button" disabled={pending || review} onClick={() => void submit('remove')}>Confirm {removeLabel.toLowerCase()}</button>
      </div>}
    </form>}
  </section>;
}
