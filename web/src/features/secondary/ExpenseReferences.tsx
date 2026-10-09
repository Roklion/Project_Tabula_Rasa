import type { FieldValues, Path, UseFormReturn } from 'react-hook-form';
import { useEntity } from '../../app/context';
import { ErrorNotice, LoadingState } from '../../components/States';
import { SelectField, TextField } from '../concurrency/Fields';
import { activeChoices, useReferenceChoices } from '../concurrency/useReferenceChoices';

type ExpenseReferences = FieldValues & { account_id: string; category_id: string; payee_id?: string; tag_ids?: string[]; description?: string; reference?: string };
const none = { id: '', name: 'None' };

export function ExpenseReferences<T extends ExpenseReferences>({ form, creating = false, inline = false }: {
  form: UseFormReturn<T>; creating?: boolean; inline?: boolean;
}) {
  const choices = useReferenceChoices(useEntity());
  const original = creating ? undefined : form.formState.defaultValues;
  const path = (name: string) => name as Path<T>;
  if (choices.pending) return <LoadingState label="Loading choices…" />;
  if (choices.error) return <ErrorNotice error={choices.error} />;
  return <>
    <SelectField form={form} name={path('account_id')} label="From account" options={[none, ...activeChoices(choices.accounts, [original?.account_id])]} />
    <SelectField form={form} name={path('category_id')} label="Expense category" options={[none, ...choices.categories.filter(row => row.kind === 'Expense')]} />
    <SelectField form={form} name={path('payee_id')} label="Payee" options={[none, ...activeChoices(choices.payees, [original?.payee_id])]} />
    <SelectField form={form} name={path('tag_ids')} label="Tags" multiple options={activeChoices(choices.tags, original?.tag_ids ?? [])} />
    {inline && <><TextField form={form} name={path('new_payee_name')} label="New payee name (optional)" />
      <TextField form={form} name={path('new_tag_name')} label="New tag name (optional)" /></>}
    <TextField form={form} name={path('description')} label="Description / memo" />
    <TextField form={form} name={path('reference')} label="Reference" />
  </>;
}
