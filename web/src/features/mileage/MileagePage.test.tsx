import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RouterProvider } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api/client';
import { createTestRouter } from '../../app/router';
import { session } from '../../test/fixtures';

it('lets read-only users inspect mileage with familiar field and tag labels', async () => {
  vi.spyOn(api, 'session').mockResolvedValue({ ...session, capabilities: ['bookkeeping:read'] });
  vi.spyOn(api, 'tags').mockResolvedValue({ items: [{ id: 'tag', name: 'Site work', active: true, baseline: 'tag-token', created_at: '' }] });
  vi.spyOn(api, 'mileageTrip').mockResolvedValue({ id: 'trip', trip_date: '2026-10-08', miles: '12.4', vehicle: 'Van',
    start_location: 'Office', destination: 'Site', business_purpose: 'Inspection', notes: 'Reviewed', tag_ids: ['tag'], created_at: '', baseline: 'opaque' });
  render(<RouterProvider router={createTestRouter(['/mileage/trip'])} />);
  expect(await screen.findByText('Inspection')).toBeVisible();
  expect(await screen.findByText('Site work')).toBeVisible();
  expect(screen.getByText('Business miles')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Save changes' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
});

it('retains an uncertain create draft and prevents another submission until the log is inspected', async () => {
  vi.spyOn(api, 'session').mockResolvedValue(session);
  vi.spyOn(api, 'tags').mockResolvedValue({ items: [] });
  const create = vi.spyOn(api, 'createMileage').mockRejectedValue(new ApiError('unavailable'));
  render(<RouterProvider router={createTestRouter(['/mileage/new'])} />);
  const purpose = await screen.findByLabelText('Business purpose');
  await userEvent.type(purpose, 'Inspection draft');
  await userEvent.type(screen.getByLabelText('Business miles'), '12.4');
  await userEvent.type(screen.getByLabelText('Starting location'), 'Office');
  await userEvent.type(screen.getByLabelText('Destination'), 'Site');
  await userEvent.click(screen.getByRole('button', { name: 'Save mileage trip' }));
  expect(await screen.findByText(/Save status is uncertain/)).toBeVisible();
  expect(purpose).toHaveValue('Inspection draft');
  expect(screen.getByRole('button', { name: 'Save mileage trip' })).toBeDisabled();
  expect(create).toHaveBeenCalledTimes(1);
});
