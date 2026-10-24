import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import styles from './MapsUsagePanel.module.css';

export function MapsUsagePanel() {
  const session = useEntity();
  const [open, setOpen] = useState(false);
  const [expired, setExpired] = useState(false);
  const configuration = useQuery({
    queryKey: resourceKey(session, 'maps-quota-status'),
    queryFn: ({ signal }) => api.mapsQuotaStatus(session, signal),
    enabled: open, staleTime: Infinity, retry: false,
    refetchOnWindowFocus: false, refetchOnReconnect: false,
  });
  const usage = useMutation({ mutationFn: (refresh: boolean) => api.loadMapsQuota(session, refresh), retry: false });
  const data = usage.data ?? configuration.data;
  useEffect(() => {
    if (usage.data?.status !== 'ready') return;
    const timer = window.setTimeout(() => setExpired(true), (usage.data.cache_remaining_seconds ?? 0) * 1000);
    return () => window.clearTimeout(timer);
  }, [usage.data]);
  const load = (refresh: boolean) => {
    setExpired(false);
    usage.mutate(refresh);
  };
  return <details className={styles.panel} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Google Maps API usage</summary>
    {open && <div className={styles.body}>
      <p>Routes and Places use a 15-minute lookback. Rows show Google’s latest sampled rate in the quota’s units.
        Reporting can lag several minutes, including up to approximately 240 seconds after sampling.
        This is not a real-time remaining-request counter or billing/spend meter.</p>
      <p>Reports are cached for up to 120 seconds. Select Refresh for current data.</p>
      {(configuration.isFetching || usage.isPending) && <p role="status">Loading usage…</p>}
      {(configuration.isError || usage.isError) && <p role="alert">Usage could not be loaded. Check your connection and business access, then retry.</p>}
      {!usage.isPending && data?.message && <p role="status">{data.message}</p>}
      {!usage.isPending && !usage.isError && data?.status === 'ready' && <>
        {data.services?.map(group => <section key={group.title} aria-label={group.title}>
          <h2>{group.title}</h2>
          {group.rows.length ? <ul>{group.rows.map((row, index) => <li key={index}>{row}</li>)}</ul>
            : <p>No Google-reported quota metrics.</p>}
        </section>)}
        {expired && <p role="status">This report is more than 120 seconds old and may be stale. Select Refresh for current data.</p>}
      </>}
      {data?.status !== 'unconfigured' && <button type="button" disabled={configuration.isFetching || usage.isPending}
        onClick={() => configuration.isError ? void configuration.refetch() : load(!!usage.data || usage.isError)}>
        {usage.data || usage.isError ? 'Refresh' : configuration.isError ? 'Retry' : 'Load usage'}
      </button>}
    </div>}
  </details>;
}
