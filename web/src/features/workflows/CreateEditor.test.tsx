import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import { ScopeBoundary } from '../../app/ScopeBoundary';
import { session } from '../../test/fixtures';
import { TextField } from '../concurrency/Fields';
import { CreateEditor } from './CreateEditor';

it('retains a create identity and draft after uncertain failure, and advances them after confirmation', async () => {
  const create = vi.fn().mockRejectedValueOnce(new ApiError('unavailable')).mockResolvedValue(undefined);
  const router = createMemoryRouter([{ path: '/', element: <ScopeBoundary session={session}>
    <CreateEditor title="Save entry" initial={() => ({ description: '' })} create={create} onClose={() => {}}
      fields={form => <TextField form={form} name="description" label="Memo" />} />
  </ScopeBoundary> }]);
  render(<RouterProvider router={router} />);
  await userEvent.type(screen.getByLabelText('Memo'), 'Preserved draft');
  await userEvent.click(screen.getByRole('button', { name: 'Save entry' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Your draft is preserved');
  expect(screen.getByLabelText('Memo')).toHaveValue('Preserved draft');
  expect(create).toHaveBeenCalledTimes(1);
  const firstIdentity = create.mock.calls[0][1];
  await userEvent.click(screen.getByRole('button', { name: 'Save entry' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Record created.');
  expect(create.mock.calls[1][1]).toBe(firstIdentity);
  expect(screen.getByLabelText('Memo')).toHaveValue('');
  await userEvent.type(screen.getByLabelText('Memo'), 'Next record');
  await userEvent.click(screen.getByRole('button', { name: 'Save entry' }));
  await waitFor(() => expect(create).toHaveBeenCalledTimes(3));
  expect(create.mock.calls[2][1]).not.toBe(firstIdentity);
});

it('preserves a draft on a closed-period rejection and explains the authorized correction path', async () => {
  const create = vi.fn().mockRejectedValue(new ApiError('period_closed'));
  const router = createMemoryRouter([{ path: '/', element: <ScopeBoundary session={session}>
    <CreateEditor title="Save entry" initial={() => ({ description: '' })} create={create} onClose={() => {}}
      fields={form => <TextField form={form} name="description" label="Memo" />} />
  </ScopeBoundary> }]);
  render(<RouterProvider router={router} />);
  await userEvent.type(screen.getByLabelText('Memo'), 'Preserved correction draft');
  await userEvent.click(screen.getByRole('button', { name: 'Save entry' }));
  const failure = await screen.findByRole('alert');
  expect(failure).toHaveTextContent('This accounting month is closed. Your draft is preserved.');
  expect(failure).toHaveTextContent('authorized reversal in an open month');
  expect(failure).toHaveTextContent('ask the Owner to unlock');
  expect(screen.getByLabelText('Memo')).toHaveValue('Preserved correction draft');
  expect(screen.queryByText('Record created.')).not.toBeInTheDocument();
  expect(create).toHaveBeenCalledTimes(1);
});
