import { useEffect } from 'react';
import type { FieldValues, Path, UseFormReturn } from 'react-hook-form';
import { ApiError } from '../api/client';

export function applyFieldErrors<T extends FieldValues>(form: UseFormReturn<T>, error: unknown) {
  if (!(error instanceof ApiError)) return;
  // Transport leaf names cannot identify a particular journal posting. Only
  // associate unambiguous top-level fields; the shared alert covers the rest.
  const values = form.getValues();
  const postingFields = new Set<string>(Array.isArray(values.postings)
    ? values.postings.flatMap(posting => Object.keys(posting)) : []);
  const fields = error.fields.filter(field => Object.hasOwn(values, field.field) && !postingFields.has(field.field));
  fields.forEach((field, index) => form.setError(field.field as Path<T>,
    { type: 'server', message: 'Check this value.' }, { shouldFocus: index === 0 }));
}

export function useServerFieldErrors<T extends FieldValues>(form: UseFormReturn<T>, error: unknown, pending: boolean) {
  useEffect(() => {
    // Catch runs before the pending fieldset is enabled. Associate/focus errors
    // after that render so keyboard users reach the affected control.
    if (!pending) applyFieldErrors(form, error);
  }, [form, error, pending]);
}
