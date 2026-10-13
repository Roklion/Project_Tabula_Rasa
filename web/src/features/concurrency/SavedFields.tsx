import type { ReactNode } from 'react';
import { useForm, type FieldValues, type UseFormReturn } from 'react-hook-form';
import { SectionHeader } from '../../components/VisualPrimitives';

export function SavedFields<T extends FieldValues>({ title, values, fields }: {
  title: string; values: T; fields: (form: UseFormReturn<T>) => ReactNode;
}) {
  const form = useForm<T>({ values });
  return <section className="surface editor" aria-label={title}><SectionHeader title={title} description="Read-only access." />
    <fieldset disabled>{fields(form)}</fieldset>
  </section>;
}
