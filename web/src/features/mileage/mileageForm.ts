import type { Schemas } from '../../api/client';

export type MileageDraft = Schemas['MileageChanges'] & { round_trip?: boolean; return_miles?: string | null };

export function mileageLoaded(row: Schemas['Mileage']) {
  const values: MileageDraft = { trip_date: row.trip_date, miles: row.miles, vehicle: row.vehicle,
    start_location: row.start_location, destination: row.destination, business_purpose: row.business_purpose,
    notes: row.notes, tag_ids: row.tag_ids, new_tag_name: '' };
  return { values, metadata: { id: row.id, baseline: row.baseline } };
}
