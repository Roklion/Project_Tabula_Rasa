import type { FieldValues, Path, UseFormReturn } from 'react-hook-form';
import { Field } from '../../components/States';

export function TextField<T extends FieldValues>({ form, name, label, type = 'text', onChange }: {
  form: UseFormReturn<T>; name: Path<T>; label: string; type?: string; onChange?: () => void;
}) {
  const error = form.getFieldState(name, form.formState).error?.message;
  return <Field id={name} label={label} error={error}><input id={name} type={type} aria-invalid={Boolean(error)}
    aria-describedby={error ? name + '-error' : undefined} {...form.register(name, { onChange })} /></Field>;
}

export function SelectField<T extends FieldValues>({ form, name, label, options, multiple = false, onChange }: {
  form: UseFormReturn<T>; name: Path<T>; label: string; options: { id: string; name: string }[]; multiple?: boolean; onChange?: () => void;
}) {
  const error = form.getFieldState(name, form.formState).error?.message;
  return <Field id={name} label={label} error={error}><select id={name} multiple={multiple} aria-invalid={Boolean(error)}
    aria-describedby={error ? name + '-error' : undefined} {...form.register(name, { onChange })}>
    {options.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}
  </select></Field>;
}

export function ActiveField<T extends FieldValues>({ form, name }: { form: UseFormReturn<T>; name: Path<T> }) {
  return <label className="checkbox"><input type="checkbox" {...form.register(name)} /> Active</label>;
}
