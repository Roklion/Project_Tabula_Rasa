import type { ReactNode } from 'react';
import { useForm, type FieldValues, type UseFormReturn } from 'react-hook-form';

export function SavedFields<T extends FieldValues>({ title, values, fields }: {
  title: string; values: T; fields: (form: UseFormReturn<T>) => ReactNode;
}) {
  const form = useForm<T>({ values });
  return <section className="surface"><h2>{title}</h2><p>Read-only access.</p>
    <fieldset disabled>{fields(form)}</fieldset>
  </section>;
}
