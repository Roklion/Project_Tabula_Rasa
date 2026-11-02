import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError, type Schemas } from '../../api/client';
import { session } from '../../test/fixtures';
import { CustomerLifecycle } from './CustomerLifecycle';

const record: Schemas['LifecycleRecord'] = { id: 'synthetic-request', requester_id: 'actor', entity_id: 'alpha',
  kind: 'business_closure', state: 'pending', effective_state: 'pending', version: 1,
  policy_version: 'customer-lifecycle-v1', created_at: '2026-11-02T00:00:00Z', confirmed_at: null,
  recover_until: null, events: [{ action: 'requested', actor_id: 'actor', occurred_at: '2026-11-02T00:00:00Z' }] };
const status: Schemas['LifecycleStatus'] = { policy_version: 'customer-lifecycle-v1', recovery_days: 60,
  deletion_available: false, deletion_blockers: ['legal_policy_unapproved'], last_owned_businesses: ['alpha'], requests: [record] };
afterEach(() => vi.restoreAllMocks());

it('previews the effects and requires saved exports before confirming business closure', async () => {
  vi.spyOn(api, 'lifecycleStatus').mockResolvedValue(status);
  const change = vi.spyOn(api, 'changeLifecycle').mockResolvedValue({ ...record, state: 'confirmed', effective_state: 'read_only', version: 2 });
  render(<CustomerLifecycle session={session} businessId="alpha" />);
  expect(await screen.findByRole('button', { name: 'Request personal login closure' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Review and confirm business closure' }));
  const dialog = screen.getByRole('alertdialog');
  expect(within(dialog).getByText(/60 days of read-only bookkeeping/)).toBeVisible();
  const confirm = within(dialog).getByRole('button', { name: 'Confirm request' });
  expect(confirm).toBeDisabled();
  fireEvent.click(within(dialog).getByRole('checkbox'));
  fireEvent.click(confirm);
  await waitFor(() => expect(change).toHaveBeenCalledExactlyOnceWith(session, record.id,
    { action: 'confirm', version: 1, export_saved: true }));
  expect(screen.getByText(/Deletion and backup pruning are unavailable/)).toBeVisible();
});

it('allows cancellation in the window and retains expired status with a support path', async () => {
  vi.spyOn(api, 'lifecycleStatus').mockResolvedValue({ ...status, requests: [{ ...record, state: 'confirmed', effective_state: 'closed_retained', recover_until: '2026-11-01T00:00:00Z' }] });
  render(<CustomerLifecycle session={session} />);
  expect(await screen.findByText('Access ended; data retained')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Cancel business closure' })).not.toBeInTheDocument();
  expect(screen.getByText(/contact your service operator through your existing private support channel/)).toBeVisible();
});

it('preserves request identity after an uncertain response and aborts status reads on unmount', async () => {
  const load = vi.spyOn(api, 'lifecycleStatus').mockResolvedValue({ ...status, requests: [] });
  const request = vi.spyOn(api, 'requestLifecycle').mockRejectedValue(new ApiError('unavailable'));
  const view = render(<CustomerLifecycle session={session} businessId="alpha" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Request business closure' }));
  await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Request business closure' }));
  await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  expect(request.mock.calls[0][1].request_id).toBe(request.mock.calls[1][1].request_id);
  const signal = load.mock.calls.at(-1)![1]!;
  view.unmount();
  expect(signal.aborted).toBe(true);
});
