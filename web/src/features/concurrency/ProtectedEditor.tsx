import { useState, type ReactNode } from 'react';
import { ConfirmationDialog } from '../../components/ConfirmationDialog';
import { useServerFieldErrors } from '../../components/fieldErrors';
import type { FieldValues, UseFormReturn } from 'react-hook-form';
import { ApiError, type Session } from '../../api/client';
import { useProtectedMutation } from './mutations';
import { useLoadedForm, type LoadedForm } from '../../components/useLoadedForm';
import { ErrorNotice, SuccessNotice } from '../../components/States';
import { UnsavedChanges } from '../../components/UnsavedChanges';

export type LoadMetadata = { id: string; baseline: string };

export function ReloadPrompt({ pending, onKeep, onReload }: { pending: boolean; onKeep: () => void; onReload: () => void }) {
  return <ConfirmationDialog title="Reload record" keepLabel="Keep draft" confirmLabel="Discard draft and reload"
    pending={pending} onKeep={onKeep} onConfirm={onReload}>
    Reload replaces your draft with the latest saved record. Review it before submitting again.
  </ConfirmationDialog>;
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
    catch (error) {
      setConfirmRemove(false); setPendingSave(undefined);
      setFailure(error);
    }
  }
  async function reloadLatest() {
    setReloading(true); setSuccess('');
    try {
      const next = await loadLatest(metadata.id);
      reload(next); setFailure(undefined); setReview(false); setConfirmRemove(false); setPendingSave(undefined);
    } catch (error) { setReview(false); setFailure(error); }
    finally { setReloading(false); }
  }
  const pending = mutation.isPending || reloading;
  useServerFieldErrors(form, failure, pending);
  return <section className="surface editor" aria-label={title}>
    <h2>{title}</h2><UnsavedChanges dirty={form.formState.isDirty} />
    {success && <SuccessNotice>{success}</SuccessNotice>}
    {onClose && <button type="button" disabled={pending} onClick={event => { event.currentTarget.focus(); if (form.formState.isDirty) setClosing(true); else onClose(); }}>Back to records</button>}
    {closing && <ConfirmationDialog title="Discard draft" keepLabel="Keep editing" confirmLabel="Discard draft and close"
      onKeep={() => setClosing(false)} onConfirm={() => { form.reset(form.getValues()); onClose?.(); }}>
      Discard your unsaved changes?
    </ConfirmationDialog>}
    {failure !== undefined && <ErrorNotice error={failure} onReview={() => setReview(true)} />}
    {review && <ReloadPrompt pending={pending} onKeep={() => setReview(false)} onReload={() => void reloadLatest()} />}
    {!removed && <form onSubmit={form.handleSubmit(values => {
      if (confirmSave?.(values, form.formState.defaultValues as Partial<T>)) setPendingSave(values);
      else void submit('save', values);
    })}>
      <fieldset disabled={pending || review}>{fields(form)}</fieldset>
      <div className="actions"><button type="submit" disabled={pending || review} onClick={event => event.currentTarget.focus()}>Save changes</button>
        <button type="button" disabled={pending || review} onClick={event => { event.currentTarget.focus(); setConfirmRemove(true); }}>{removeLabel}</button></div>
      {pendingSave !== undefined && <ConfirmationDialog title="Deactivate record" keepLabel="Keep editing"
        confirmLabel="Confirm deactivate" pending={pending || review} onKeep={() => setPendingSave(undefined)}
        onConfirm={() => void submit('save', pendingSave)}>
        Deactivate this record and save your changes? The saved record must still match the one you loaded.
      </ConfirmationDialog>}
      {confirmRemove && <ConfirmationDialog title={removeLabel + ' record'} keepLabel="Keep record"
        confirmLabel={'Confirm ' + removeLabel.toLowerCase()} pending={pending || review}
        onKeep={() => setConfirmRemove(false)} onConfirm={() => void submit('remove')}>
        {removeLabel === 'Delete' ? 'Permanently delete this record?' : 'Deactivate this account?'} The saved record must still match the one you loaded.
      </ConfirmationDialog>}
    </form>}
  </section>;
}
