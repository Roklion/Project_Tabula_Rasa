import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { UseFormReturn } from 'react-hook-form';
import { api, type Schemas } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { TextField } from '../concurrency/Fields';
import { FormSection } from '../../components/VisualPrimitives';
import { MapsAddress, type SelectedPlace } from './MapsAddress';
import type { MileageDraft } from './mileageForm';

export function MapsMileageFields({ form, children }: { form: UseFormReturn<MileageDraft>; children: ReactNode }) {
  const session = useEntity();
  const configuration = useQuery({ queryKey: resourceKey(session, 'mileage-maps'), queryFn: ({ signal }) => api.mileageMaps(session, signal), retry: false });
  const [origin, setOrigin] = useState<SelectedPlace>();
  const [destination, setDestination] = useState<SelectedPlace>();
  const [route, setRoute] = useState<Schemas['MileageRoute']>();
  const [busy, setBusy] = useState(false);
  const [googleContent, setGoogleContent] = useState(false);
  const [failure, setFailure] = useState(false);
  const [recordedMismatch, setRecordedMismatch] = useState(false);
  const generation = useRef(0);
  const request = useRef<AbortController | undefined>(undefined);
  const calculated = useRef<{ outbound?: string; returned?: string }>({});
  const roundTrip = !!form.watch('round_trip');
  const maps = configuration.data;
  useEffect(() => () => { generation.current += 1; request.current?.abort(); }, []);
  useEffect(() => {
    const subscription = form.watch((_, event) => {
      if (event.name !== 'round_trip') return;
      generation.current += 1;
      setBusy(false);
      setRoute(previous => previous ? { ...previous, return_miles: null, error_code: null } : previous);
      calculated.current.returned = undefined;
      form.setValue('maps_reviewed', false);
    });
    return () => subscription.unsubscribe();
  }, [form]);
  const resetRoute = useCallback(() => {
    generation.current += 1; setBusy(false); setRoute(undefined); setFailure(false);
    // Clear only unchanged provisional calculations; preserve user-entered miles.
    if (calculated.current.outbound !== undefined && form.getValues('miles') === calculated.current.outbound) form.setValue('miles', '', { shouldDirty: true });
    if (calculated.current.returned !== undefined && form.getValues('return_miles') === calculated.current.returned) form.setValue('return_miles', '', { shouldDirty: true });
    calculated.current = {}; form.setValue('maps_reviewed', false);
  }, [form]);
  const clearOrigin = useCallback(() => { setOrigin(undefined); resetRoute(); }, [resetRoute]);
  const clearDestination = useCallback(() => { setDestination(undefined); resetRoute(); }, [resetRoute]);
  const selectOrigin = useCallback((place: SelectedPlace) => { setOrigin(place); resetRoute(); setGoogleContent(true);
    form.setValue('start_location', place.text, { shouldDirty: true }); }, [form, resetRoute]);
  const selectDestination = useCallback((place: SelectedPlace) => { setDestination(place); resetRoute(); setGoogleContent(true);
    form.setValue('destination', place.text, { shouldDirty: true }); }, [form, resetRoute]);
  const reviewAgain = () => form.setValue('maps_reviewed', false);
  const recordedChanged = () => { setRecordedMismatch(true); reviewAgain(); };
  async function calculate() {
    if (!origin || !destination || busy) return;
    const current = ++generation.current;
    request.current?.abort();
    request.current = new AbortController();
    setBusy(true); setFailure(false); setRoute(undefined); reviewAgain();
    try {
      const result = await api.calculateMileageRoute(session, { origin_place_id: origin.placeId, destination_place_id: destination.placeId, round_trip: roundTrip }, request.current.signal);
      if (current !== generation.current) return;
      setRoute(result);
      if (result.outbound_miles) {
        form.setValue('miles', result.outbound_miles, { shouldDirty: true });
        calculated.current.outbound = result.outbound_miles; setGoogleContent(true);
      }
      if (roundTrip && result.return_miles) {
        form.setValue('return_miles', result.return_miles, { shouldDirty: true }); calculated.current.returned = result.return_miles;
      }
    } catch { if (current === generation.current) setFailure(true); }
    finally { if (current === generation.current) setBusy(false); }
  }
  const error = form.getFieldState('maps_reviewed', form.formState).error?.message;
  const routeCurrent = !!route?.outbound_miles && (!roundTrip || !!route.return_miles);
  return <><FormSection title="Route and mileage" description="Enter locations and mileage manually or review optional Maps suggestions.">
    {maps?.browser_api_key && <><MapsAddress browserKey={maps.browser_api_key} regionCode={maps.region_code ?? null} label="Starting location lookup" onSelect={selectOrigin} onClear={clearOrigin} />
      <MapsAddress browserKey={maps.browser_api_key} regionCode={maps.region_code ?? null} label="Destination lookup" onSelect={selectDestination} onClear={clearDestination} />
      <p className="muted">Google suggestions are used for route lookup. Review or edit the location text to record below.</p></>}
    <TextField form={form} name="start_location" label="Starting location" onChange={recordedChanged} />
    <TextField form={form} name="destination" label="Destination" onChange={recordedChanged} />
    {recordedMismatch && maps?.browser_api_key && <p role="status">The recorded location changed. Check that the mileage still matches the travel you are recording.</p>}
    {maps?.browser_api_key && maps.routes_available ? <>
      <button type="button" disabled={busy || !origin || !destination || origin.placeId === destination.placeId} onClick={() => void calculate()}>Calculate mileage</button>
      {busy && <p role="status">Calculating mileage…</p>}
      {!routeCurrent && <p role="status">Current mileage has not been compared with this route. Enter or review miles manually, or calculate mileage.</p>}
    </> : <p className="muted">Google Maps lookup or routing is unavailable. Enter locations and mileage manually.</p>}
    {(route?.error_code || failure) && <p role="alert">{route?.outbound_miles ? 'Outbound mileage was calculated, but the return route failed. ' : ''}
      {route?.error_code === 'quota' ? 'Google Maps quota has been reached. ' : route?.error_code === 'no_route' ? 'Google Maps did not return a usable route. ' : 'Google Maps routing is unavailable. '}
      Enter miles manually or try Calculate mileage again.</p>}
    <TextField form={form} name="miles" label="Business miles" inputMode="decimal" onChange={reviewAgain} />
    {roundTrip && <TextField form={form} name="return_miles" label="Return business miles" inputMode="decimal" onChange={reviewAgain} />}
    </FormSection>
    {children}
    {googleContent && <p role="note" translate="no" aria-label="Google Maps attribution">Google Maps</p>}
    {googleContent && <label className="checkbox"><input type="checkbox" {...form.register('maps_reviewed', {
      validate: value => !googleContent || value === true || 'Review and confirm the recorded locations and mileage before saving.',
    })} /> I reviewed the recorded locations and mileage</label>}{googleContent && error && <p role="alert">{error}</p>}
  </>;
}
