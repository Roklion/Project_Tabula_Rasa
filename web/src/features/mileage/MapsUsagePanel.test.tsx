import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api, type Schemas } from '../../api/client';
import { ScopeBoundary } from '../../app/ScopeBoundary';
import { session } from '../../test/fixtures';
import { MapsUsagePanel } from './MapsUsagePanel';

vi.mock('../../api/client', () => ({ api: { mapsQuotaStatus: vi.fn(), loadMapsQuota: vi.fn() } }));

const ready = { status: 'ready', message: null, cache_remaining_seconds: 120,
  services: [{ title: 'Routes API', rows: ['ComputeRoutes: 120/Unlimited (per minute)'] },
    { title: 'Places API (New)', rows: ['Autocomplete requests: 0/60 (per minute)'] }] } satisfies Schemas['MapsQuotaStatus'];

beforeEach(() => {
  vi.mocked(api.mapsQuotaStatus).mockResolvedValue({ status: 'not_loaded', message: null, services: [], cache_remaining_seconds: 0 });
  vi.mocked(api.loadMapsQuota).mockResolvedValue(ready);
});
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });

function panel() {
  return render(<ScopeBoundary session={session}><MapsUsagePanel /></ScopeBoundary>);
}

async function expand() {
  fireEvent.click(screen.getByText('Google Maps API usage'));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Load usage' })).toBeEnabled());
}

it('loads only on explicit request and keeps refresh isolated with no focus/reconnect polling', async () => {
  panel();
  expect(api.mapsQuotaStatus).not.toHaveBeenCalled();
  expect(api.loadMapsQuota).not.toHaveBeenCalled();
  await expand();
  expect(api.mapsQuotaStatus).toHaveBeenCalledTimes(1);
  expect(api.loadMapsQuota).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Load usage' }));
  expect(await screen.findByText(ready.services[0].rows[0])).toBeVisible();
  expect(screen.getByRole('region', { name: 'Places API (New)' })).toHaveTextContent(ready.services[1].rows[0]);
  expect(api.loadMapsQuota).toHaveBeenLastCalledWith(session, false);
  fireEvent(window, new Event('focus'));
  fireEvent(window, new Event('online'));
  fireEvent.click(screen.getByText('Google Maps API usage'));
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Refresh' })).not.toBeInTheDocument());
  fireEvent.click(screen.getByText('Google Maps API usage'));
  await screen.findByRole('button', { name: 'Refresh' });
  expect(api.loadMapsQuota).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
  await waitFor(() => expect(api.loadMapsQuota).toHaveBeenCalledTimes(2));
  expect(api.loadMapsQuota).toHaveBeenLastCalledWith(session, true);
  expect(screen.getByText(/15-minute lookback/)).toHaveTextContent(/240 seconds/);
  expect(screen.getByText(/15-minute lookback/)).toHaveTextContent(/not a real-time remaining-request counter or billing\/spend meter/);
});

it('shows setup guidance without offering a provider request when unconfigured', async () => {
  vi.mocked(api.mapsQuotaStatus).mockResolvedValue({ status: 'unconfigured', message: 'Configure the dedicated Maps quota reader.', services: [], cache_remaining_seconds: 0 });
  panel();
  fireEvent.click(screen.getByText('Google Maps API usage'));
  await screen.findByText('Configure the dedicated Maps quota reader.');
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
  expect(api.loadMapsQuota).not.toHaveBeenCalled();
});

it('shows sanitized provider guidance and refresh failure removes old rows without automatic retry', async () => {
  panel(); await expand();
  fireEvent.click(screen.getByRole('button', { name: 'Load usage' }));
  await screen.findByText(ready.services[0].rows[0]);
  vi.mocked(api.loadMapsQuota).mockResolvedValue({ status: 'error', message: 'Cloud Monitoring request returned HTTP 403. Verify the quota-reader OAuth scopes and IAM roles.', services: [], cache_remaining_seconds: 0 });
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
  await screen.findByText(/Cloud Monitoring request returned HTTP 403/);
  expect(screen.queryByText(ready.services[0].rows[0])).not.toBeInTheDocument();
  expect(api.loadMapsQuota).toHaveBeenCalledTimes(2);
});

it('keeps transport errors safe and offers an explicit retry', async () => {
  vi.mocked(api.loadMapsQuota).mockRejectedValue(new Error('private-provider-text'));
  panel(); await expand();
  fireEvent.click(screen.getByRole('button', { name: 'Load usage' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('business access');
  expect(screen.queryByText(/private-provider-text/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Refresh' })).toBeEnabled();
  expect(api.loadMapsQuota).toHaveBeenCalledTimes(1);
});

it('marks an expired report without issuing another request', async () => {
  panel(); await expand();
  fireEvent.click(screen.getByRole('button', { name: 'Load usage' }));
  await screen.findByText(ready.services[0].rows[0]);
  vi.useFakeTimers();
  // A second explicit result starts a bounded display-expiry timer.
  vi.mocked(api.loadMapsQuota).mockResolvedValue({ ...ready, cache_remaining_seconds: 1 });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh' })); await vi.advanceTimersByTimeAsync(10); });
  await act(async () => { await vi.advanceTimersByTimeAsync(121_000); });
  expect(screen.getByRole('status')).toHaveTextContent('may be stale');
  expect(api.loadMapsQuota).toHaveBeenCalledTimes(2);
});

it.each(['business', 'sign-out'])('discards pending results and resets the panel on %s changes', async change => {
  let finish!: (value: Schemas['MapsQuotaStatus']) => void;
  vi.mocked(api.loadMapsQuota).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const view = panel(); await expand();
  fireEvent.click(screen.getByRole('button', { name: 'Load usage' }));
  await waitFor(() => expect(api.loadMapsQuota).toHaveBeenCalledTimes(1));
  const next = { ...session, cache_scope: 'next-session', entity: { id: 'beta', name: 'Beta' } };
  if (change === 'sign-out') view.rerender(<div>Signed out</div>);
  else view.rerender(<ScopeBoundary session={next}><MapsUsagePanel /></ScopeBoundary>);
  await act(async () => { finish(ready); });
  expect(screen.queryByText(ready.services[0].rows[0])).not.toBeInTheDocument();
  if (change === 'sign-out') view.rerender(<ScopeBoundary session={next}><MapsUsagePanel /></ScopeBoundary>);
  expect(screen.getByText('Google Maps API usage').closest('details')).not.toHaveAttribute('open');
  expect(api.loadMapsQuota).toHaveBeenCalledTimes(1);
  await expand();
  fireEvent.click(screen.getByRole('button', { name: 'Load usage' }));
  await screen.findByText(ready.services[0].rows[0]);
  expect(api.loadMapsQuota).toHaveBeenLastCalledWith(next, false);
});
