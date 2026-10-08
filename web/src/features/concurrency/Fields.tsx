import type { FieldValues, Path, UseFormReturn } from 'react-hook-form';
import { Field } from '../../components/States';

export function TextField<T extends FieldValues>({ form, name, label, type = 'text' }: {
  form: UseFormReturn<T>; name: Path<T>; label: string; type?: string;
}) {
  return <Field id={name} label={label}><input id={name} type={type} {...form.register(name)} /></Field>;
}

export function SelectField<T extends FieldValues>({ form, name, label, options, multiple = false, onChange }: {
  form: UseFormReturn<T>; name: Path<T>; label: string; options: { id: string; name: string }[]; multiple?: boolean; onChange?: () => void;
}) {
  return <Field id={name} label={label}><select id={name} multiple={multiple} {...form.register(name, { onChange })}>
    {options.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}
  </select></Field>;
}

export function ActiveField<T extends FieldValues>({ form, name }: { form: UseFormReturn<T>; name: Path<T> }) {
  return <label className="checkbox"><input type="checkbox" {...form.register(name)} /> Active</label>;
}
