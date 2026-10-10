import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, ApiError, type Schemas } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { EmptyState, ErrorNotice, Field, LoadingState, SuccessNotice } from '../../components/States';
import { UnsavedChanges } from '../../components/UnsavedChanges';
import { ProtectedEditor } from '../concurrency/ProtectedEditor';
import { useProtectedMutation } from '../concurrency/mutations';
import { MileageFields } from './MileageFields';
import { mileageLoaded, type MileageDraft } from './mileageForm';
import { mileageCsvCell } from './mileageCsv';
import { downloadBlob } from '../../components/downloadBlob';
import { localDate } from '../../components/localDate';

const tripLabel = (row: Schemas['Mileage']) => `${row.trip_date} · ${row.destination} · ${row.miles} miles`;

export function MileagePage() {
  const session = useEntity();
  const navigate = useNavigate();
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [tagIds, setTagIds] = useState<string[]>([]);
  const trips = useQuery({ queryKey: resourceKey(session, 'mileage'), queryFn: ({ signal }) => api.mileage(session, signal) });
  const tags = useQuery({ queryKey: resourceKey(session, 'tags'), queryFn: ({ signal }) => api.tags(session, signal) });
  const names = new Map(tags.data?.items.map(tag => [tag.id, tag.name]));
  const rows = (trips.data?.items ?? []).filter(row => (!start || row.trip_date >= start) && (!end || row.trip_date <= end)
    && (!tagIds.length || row.tag_ids.some(id => tagIds.includes(id))));
  function download() {
    const data = [['ID', 'Date', 'Miles', 'From', 'Destination', 'Business purpose', 'Vehicle', 'Tags', 'Notes'],
      ...rows.map(row => [row.id, row.trip_date, row.miles, row.start_location, row.destination, row.business_purpose,
        row.vehicle, row.tag_ids.map(id => names.get(id) ?? id).join('; '), row.notes])];
    downloadBlob(new Blob([data.map(row => row.map(mileageCsvCell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' }), 'tabula-rasa-mileage.csv');
  }
  return <><h1>Mileage</h1><p className="lead">Record business travel and review your mileage log.</p>
    {session.capabilities.includes('bookkeeping:write') && <Link className="button" to="/mileage/new">Add trip</Link>}
    <section className="surface editor" aria-label="Mileage filters"><h2>View &amp; edit mileage log</h2><div className="formGrid">
      <Field id="from" label="From"><input id="from" type="date" value={start} onChange={e => setStart(e.target.value)} /></Field>
      <Field id="to" label="To"><input id="to" type="date" value={end} onChange={e => setEnd(e.target.value)} /></Field>
      {tags.isPending ? <LoadingState label="Loading tags…" /> : tags.isError ? <ErrorNotice error={tags.error} onReview={() => void tags.refetch()} />
        : <Field id="filter-tags" label="Filter by tags"><select id="filter-tags" multiple value={tagIds}
          onChange={e => setTagIds(Array.from(e.target.selectedOptions, option => option.value))}>
          {tags.data.items.map(tag => <option key={tag.id} value={tag.id}>{tag.name}</option>)}
        </select></Field>}
    </div><button type="button" onClick={() => { setStart(''); setEnd(''); setTagIds([]); }}>Clear filters</button></section>
    {trips.isPending ? <LoadingState label="Loading mileage…" /> : trips.isError ? <ErrorNotice error={trips.error} onReview={() => void trips.refetch()} /> : <>
      <p role="status">Trips: {rows.length} · Business miles: {(rows.reduce((sum, row) => sum + Math.round(Number(row.miles) * 10), 0) / 10).toFixed(1)}</p>
      <button type="button" disabled={!rows.length} onClick={download}>Download filtered mileage CSV</button>
      {!rows.length ? <EmptyState title="No mileage trips">Add a trip or adjust the filters.</EmptyState> :
        <div className="tableScroll" role="region" aria-label="Mileage log" tabIndex={0}><table><caption>Business mileage</caption>
          <thead><tr>{['Date', 'Miles', 'From', 'Destination', 'Business purpose', 'Vehicle', 'Tags', 'Notes', 'ID', 'Actions'].map(label => <th key={label}>{label}</th>)}</tr></thead>
          <tbody>{rows.map(row => <tr key={row.id}><th scope="row">{row.trip_date}</th><td className="amount">{row.miles}</td><td>{row.start_location}</td>
            <td>{row.destination}</td><td>{row.business_purpose}</td><td>{row.vehicle}</td><td>{row.tag_ids.map(id => names.get(id) ?? id).join(', ')}</td><td>{row.notes}</td><td>{row.id}</td>
            <td><button type="button" onClick={() => navigate('/mileage/' + encodeURIComponent(row.id))}>
              {session.capabilities.includes('bookkeeping:write') ? 'Edit ' : 'View '}{tripLabel(row)}</button></td></tr>)}</tbody>
        </table></div>}
    </>}
  </>;
}

export function NewMileage() {
  const session = useEntity();
  const form = useForm<MileageDraft>({ defaultValues: { trip_date: localDate(),
    miles: '', vehicle: '', start_location: '', destination: '', business_purpose: '', notes: '', tag_ids: [], new_tag_name: '', round_trip: false } });
  const [failure, setFailure] = useState<unknown>();
  const [created, setCreated] = useState<Schemas['Mileage'][]>([]);
  const [uncertain, setUncertain] = useState(false);
  const mutation = useProtectedMutation(session, async (values: MileageDraft) => {
    const response = await api.createMileage(session, { ...values, round_trip: !!values.round_trip, return_miles: values.round_trip ? values.return_miles : null });
    setCreated(response.items); form.reset(values);
  });
  if (!session.capabilities.includes('bookkeeping:write')) return <ErrorNotice error={new ApiError('forbidden')} />;
  return <><h1>Add trip</h1><Link to="/mileage">View mileage log</Link><UnsavedChanges dirty={form.formState.isDirty} />
    {created.length ? <><SuccessNotice>Mileage saved: {created.length} {created.length === 1 ? 'trip' : 'trips'}.</SuccessNotice>
      {created.map(row => <p key={row.id}><Link to={'/mileage/' + encodeURIComponent(row.id)}>{tripLabel(row)}</Link></p>)}</> :
      <form className="surface editor" onSubmit={form.handleSubmit(async values => {
        setFailure(undefined);
        try { await mutation.mutateAsync(values); } catch (error) {
          setFailure(error); setUncertain(!(error instanceof ApiError && ['validation', 'reference', 'required', 'invariant', 'forbidden', 'unauthorized'].includes(error.code)));
        }
      })}>
        {failure !== undefined && <ErrorNotice error={failure} />}
        {uncertain && <p role="alert">Save status is uncertain. Review the mileage log before starting another entry.</p>}
        <fieldset disabled={mutation.isPending || uncertain}>
          <label className="checkbox"><input type="checkbox" {...form.register('round_trip', { onChange: () => {
            if (form.getValues('round_trip')) form.setValue('return_miles', form.getValues('miles'));
          } })} /> Round trip</label>
          <p className="muted">A round trip saves two independent trips with reversed locations. Review both distances before saving.</p>
          <MileageFields form={form} />
        </fieldset>
        <div className="actions"><button type="submit" disabled={mutation.isPending || uncertain}>Save mileage trip</button></div>
        {mutation.isPending && <LoadingState label="Saving mileage…" />}
      </form>}
  </>;
}

export function MileageDetail() {
  const { recordId = '' } = useParams();
  return <MileageDetailQuery key={recordId} recordId={recordId} />;
}

function MileageDetailQuery({ recordId }: { recordId: string }) {
  const session = useEntity();
  const navigate = useNavigate();
  const [initialized, setInitialized] = useState(false);
  const tags = useQuery({ queryKey: resourceKey(session, 'tags'), queryFn: ({ signal }) => api.tags(session, signal) });
  const query = useQuery({ queryKey: [...resourceKey(session, 'mileage'), recordId],
    queryFn: ({ signal }) => api.mileageTrip(session, recordId, signal), staleTime: 0, refetchOnMount: 'always' });
  // Wait for this visit's read, then let useLoadedForm retain the draft/baseline.
  if (!initialized && query.isFetchedAfterMount && query.isSuccess) setInitialized(true);
  return <><h1>Mileage trip</h1>{!initialized && (!query.isFetchedAfterMount || query.isPending) ? <LoadingState />
    : (query.isError && !initialized) || !query.data ? <ErrorNotice error={query.error} onReview={() => void query.refetch()} />
    : session.capabilities.includes('bookkeeping:write') ? <ProtectedEditor key={recordId} session={session} loaded={mileageLoaded(query.data)} title="Edit mileage trip"
      onClose={() => navigate('/mileage')} fields={form => <MileageFields form={form} />}
      save={async (id, baseline, changes) => mileageLoaded(await api.updateMileage(session, id, { baseline, changes }))}
      remove={(id, baseline) => api.deleteMileage(session, id, baseline)}
      loadLatest={async id => mileageLoaded(await api.mileageTrip(session, id))} />
    : <section className="surface"><h2>{tripLabel(query.data)}</h2><dl>
      {([['Trip date', query.data.trip_date], ['Vehicle', query.data.vehicle], ['Business miles', query.data.miles],
        ['Starting location', query.data.start_location], ['Destination', query.data.destination], ['Business purpose', query.data.business_purpose],
        ['Notes', query.data.notes], ['Tags', query.data.tag_ids.map(id => tags.data?.items.find(tag => tag.id === id)?.name ?? 'Unavailable tag').join(', ')]])
        .map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || 'None'}</dd></div>)}
    </dl><Link to="/mileage">Back to records</Link></section>}
  </>;
}
