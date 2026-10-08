import { useState } from 'react';
import { useForm, type DefaultValues, type FieldValues } from 'react-hook-form';

export type LoadedForm<T, M> = { values: T; metadata: Readonly<M> };

export function useLoadedForm<T extends FieldValues, M>(loaded: LoadedForm<T, M>) {
  // Captured once; background refetches cannot change the draft or its baseline.
  // Explicit reload is the only way to replace the loaded snapshot.
  const form = useForm<T>({ defaultValues: structuredClone(loaded.values) as DefaultValues<T> });
  const [metadata, setMetadata] = useState<Readonly<M>>(() => Object.freeze(structuredClone(loaded.metadata)));
  function reload(next: LoadedForm<T, M>) {
    setMetadata(Object.freeze(structuredClone(next.metadata)));
    form.reset(structuredClone(next.values));
  }
  return { form, metadata, reload };
}
