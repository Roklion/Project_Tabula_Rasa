import { useQuery } from '@tanstack/react-query';
import type { UseFormReturn } from 'react-hook-form';
import { api } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { ErrorNotice, LoadingState } from '../../components/States';
import { SelectField, TextField } from '../concurrency/Fields';
import { activeChoices } from '../concurrency/useReferenceChoices';
import type { MileageDraft } from './mileageForm';
import { FormSection } from '../../components/VisualPrimitives';

export function MileageFields({ form }: { form: UseFormReturn<MileageDraft> }) {
  const session = useEntity();
  const tags = useQuery({ queryKey: resourceKey(session, 'tags'), queryFn: ({ signal }) => api.tags(session, signal) });
  return <><FormSection title="Trip details">
    <TextField form={form} name="trip_date" label="Trip date" type="date" />
    <TextField form={form} name="vehicle" label="Vehicle" />
    <TextField form={form} name="miles" label="Business miles" inputMode="decimal" />
    {form.watch('round_trip') && <TextField form={form} name="return_miles" label="Return business miles" inputMode="decimal" />}
    </FormSection><FormSection title="Route and purpose" description="Enter the locations and distance manually. Review both distances for a round trip.">
    <TextField form={form} name="start_location" label="Starting location" />
    <TextField form={form} name="destination" label="Destination" />
    <TextField form={form} name="business_purpose" label="Business purpose" multiline />
    <TextField form={form} name="notes" label="Notes" multiline />
    </FormSection><FormSection title="Tags">
    {tags.isPending ? <LoadingState label="Loading tags…" /> : tags.isError ? <ErrorNotice error={tags.error} onReview={() => void tags.refetch()} />
      : <SelectField form={form} name="tag_ids" label="Tags" options={activeChoices(tags.data.items, form.formState.defaultValues?.tag_ids ?? [])} multiple />}
    <TextField form={form} name="new_tag_name" label="New tag name (optional)" />
    </FormSection></>;
}
