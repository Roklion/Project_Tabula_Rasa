import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import { createPrivateCache } from '../../api/query';
import { EntityContext } from '../../app/context';
import { session } from '../../test/fixtures';
import { ConnectionsPanel } from './ConnectionsPanel';

afterEach(() => vi.restoreAllMocks());

function show(cache = createPrivateCache()) {
  return render(<QueryClientProvider client={cache}><EntityContext.Provider
    value={{ ...session, trusted_development: false, capabilities: [...session.capabilities, 'connections:manage'] }}>
    <ConnectionsPanel />
  </EntityContext.Provider></QueryClientProvider>);
}

it('requires explicit confirmation and sends only the loaded revision and action', async () => {
  const status = vi.spyOn(api, 'connectionStatus').mockResolvedValue({ provider: 'google_drive', self_service_available: false, status: 'pending', revision: 7 });
  const change = vi.spyOn(api, 'changeConnection').mockImplementation(async () => {
    status.mockResolvedValue({ provider: 'google_drive', self_service_available: false, status: 'connected', revision: 8 });
    return { provider: 'google_drive', self_service_available: false, status: 'connected', revision: 8 };
  });
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Connect Google Drive' }));
  expect(change).not.toHaveBeenCalled();
  const dialog = screen.getByRole('alertdialog', { name: 'Connect Google Drive' });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Connect Google Drive' }));
  expect(await screen.findByText('Google Drive is connected for this business.')).toBeVisible();
  expect(change.mock.calls[0][1]).toEqual({ revision: 7, connect: true });
  fireEvent.click(await screen.findByRole('button', { name: 'Disconnect Google Drive' }));
  expect(screen.getByText(/does not revoke Google consent/)).toBeVisible();
  fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Cancel' }));
  expect(change).toHaveBeenCalledTimes(1);
});

it('keeps failure visible, reloads status and never retries an uncertain command', async () => {
  vi.spyOn(api, 'connectionStatus').mockResolvedValue({ provider: 'google_drive', self_service_available: false, status: 'disconnected', revision: 3 });
  const change = vi.spyOn(api, 'changeConnection').mockRejectedValue(new ApiError('unavailable'));
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Reconnect Google Drive' }));
  fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Reconnect Google Drive' }));
  expect(await screen.findByRole('alert')).toBeVisible();
  expect(change).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('Google Drive is connected for this business.')).not.toBeInTheDocument();
});

it('shows operator setup when no grant exists', async () => {
  const status = vi.spyOn(api, 'connectionStatus').mockResolvedValue({
    provider: 'google_drive', self_service_available: false, status: 'not_configured', revision: 0 });
  const view = show();
  expect(await screen.findByText('Not connected')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Connect Google Drive' })).not.toBeInTheDocument();
  expect(screen.getByText(/operator provisions/)).toBeVisible();
  view.unmount();
  expect(status).toHaveBeenCalledTimes(1);
});

it('cancels an unfinished status read on unmount', () => {
  const status = vi.spyOn(api, 'connectionStatus').mockReturnValue(new Promise(() => undefined));
  const view = show();
  const signal = status.mock.calls[0][1]!;
  view.unmount();
  expect(signal.aborted).toBe(true);
});

it('offers first-time customer consent and sends only the reviewed revision', async () => {
  vi.spyOn(api, 'connectionStatus').mockResolvedValue({ provider: 'google_drive', status: 'not_configured',
    revision: 0, self_service_available: true });
  const authorize = vi.spyOn(api, 'authorizeDrive').mockRejectedValue(new ApiError('unavailable'));
  const change = vi.spyOn(api, 'changeConnection');
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Connect Google Drive' }));
  expect(screen.getByRole('alertdialog')).toHaveTextContent('Continue to Google');
  fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Connect Google Drive' }));
  expect(await screen.findByRole('alert')).toBeVisible();
  expect(authorize).toHaveBeenCalledTimes(1);
  expect(authorize.mock.calls[0][1]).toEqual({ revision: 0 });
  expect(change).not.toHaveBeenCalled();
});

it('shows a safe account and incomplete consent guidance with a deliberate retry', async () => {
  vi.spyOn(api, 'connectionStatus').mockResolvedValue({ provider: 'google_drive', status: 'disconnected',
    revision: 3, self_service_available: true, authorization_status: 'failed', authorized_account: 'synthetic@example.test' });
  show();
  expect(await screen.findByText('Google account: synthetic@example.test')).toBeVisible();
  expect(screen.getByRole('alert')).toHaveTextContent('Reconnect the original account');
  expect(screen.getByRole('button', { name: 'Reconnect Google Drive' })).toBeEnabled();
});

it('keeps the reviewed grant revision when status refreshes during confirmation', async () => {
  const status = vi.spyOn(api, 'connectionStatus').mockResolvedValue({ provider: 'google_drive', self_service_available: false, status: 'pending', revision: 7 });
  const change = vi.spyOn(api, 'changeConnection').mockRejectedValue(new ApiError('concurrent_write'));
  const cache = createPrivateCache();
  show(cache);
  fireEvent.click(await screen.findByRole('button', { name: 'Connect Google Drive' }));
  status.mockResolvedValue({ provider: 'google_drive', self_service_available: false, status: 'pending', revision: 8 });
  await act(async () => { await cache.invalidateQueries(); });
  fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Connect Google Drive' }));
  expect(await screen.findByRole('alert')).toBeVisible();
  expect(change.mock.calls[0][1]).toEqual({ revision: 7, connect: true });
});
