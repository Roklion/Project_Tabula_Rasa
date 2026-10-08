import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RouterProvider } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { session } from '../test/fixtures';
import { createTestRouter } from './router';

it('loads server context and navigates without rerun semantics', async () => {
  vi.spyOn(api, 'session').mockResolvedValue(session);
  vi.spyOn(api, 'accounts').mockResolvedValue({ items: [] });
  render(<RouterProvider router={createTestRouter()} />);
  expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeVisible();
  await userEvent.click(screen.getByRole('link', { name: 'Accounts' }));
  expect(await screen.findByRole('heading', { name: 'No accounts yet' })).toBeVisible();
  expect(screen.getAllByText('Alpha').length).toBeGreaterThan(0);
});

it('shows visible safe conflict state and an explicit reload action', async () => {
  vi.spyOn(api, 'session').mockResolvedValue(session);
  vi.spyOn(api, 'accounts').mockRejectedValue(new ApiError('stale', 'safe-reference'));
  render(<RouterProvider router={createTestRouter(['/accounts'])} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Your draft is preserved');
  expect(screen.getByRole('button', { name: 'Review latest record' })).toBeVisible();
  expect(screen.getByText(/safe-reference/)).toBeVisible();
});

it('fails closed without a server context and never loads bookkeeping', async () => {
  vi.spyOn(api, 'session').mockRejectedValue(new ApiError('unauthorized'));
  const accounts = vi.spyOn(api, 'accounts');
  render(<RouterProvider router={createTestRouter(['/accounts'])} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Business access is unavailable');
  expect(accounts).not.toHaveBeenCalled();
});
