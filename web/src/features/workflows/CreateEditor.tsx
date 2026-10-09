import { useState, type ReactNode } from 'react';
import { ConfirmationDialog } from '../../components/ConfirmationDialog';
import { useServerFieldErrors } from '../../components/fieldErrors';
import { useForm, useWatch, type DefaultValues, type FieldValues, type UseFormReturn } from 'react-hook-form';
import { useEntity } from '../../app/context';
import { ErrorNotice, SuccessNotice } from '../../components/States';
import { UnsavedChanges } from '../../components/UnsavedChanges';
import { useProtectedMutation } from '../concurrency/mutations';

export function CreateEditor<T extends FieldValues>({ title, initial, fields, create, onClose, canSubmit = () => true }: {
  title: string; initial: () => T; fields: (form: UseFormReturn<T>) => ReactNode;
  create: (values: T, identity: string) => Promise<unknown>; onClose: () => void; canSubmit?: (values: T) => boolean;
}) {
  const session = useEntity();
  const [defaults] = useState(initial);
  const [identity, setIdentity] = useState(() => crypto.randomUUID());
  const form = useForm<T>({ defaultValues: defaults as DefaultValues<T> });
  const values = useWatch({ control: form.control }) as T;
  const [failure, setFailure] = useState<unknown>();
  const [success, setSuccess] = useState(false);
  const [closing, setClosing] = useState(false);
  const mutation = useProtectedMutation(session, async (values: T) => {
    await create(values, identity);
    form.reset(initial());
    setIdentity(crypto.randomUUID());
    setSuccess(true);
  });
  useServerFieldErrors(form, failure, mutation.isPending);
  async function submit(values: T) {
    setFailure(undefined); setSuccess(false);
    try { await mutation.mutateAsync(values); }
    catch (error) { setFailure(error); }
  }
  return <section className="surface editor" aria-label={title}><h2>{title}</h2>
    <UnsavedChanges dirty={form.formState.isDirty} />
    {success && <SuccessNotice>Record created.</SuccessNotice>}
    {failure !== undefined && <ErrorNotice error={failure} />}
    <form onSubmit={form.handleSubmit(values => void submit(values))}>
      <fieldset disabled={mutation.isPending}>{fields(form)}</fieldset>
      <div className="actions"><button type="submit" disabled={mutation.isPending || !canSubmit(values)}>{title}</button>
        <button type="button" disabled={mutation.isPending} onClick={event => { event.currentTarget.focus(); if (form.formState.isDirty) setClosing(true); else onClose(); }}>Back to records</button></div>
    </form>
    {closing && <ConfirmationDialog title="Discard draft" keepLabel="Keep editing" confirmLabel="Discard draft and close"
      onKeep={() => setClosing(false)} onConfirm={() => { form.reset(); onClose(); }}>
      Discard this unsaved draft?
    </ConfirmationDialog>}
  </section>;
}
