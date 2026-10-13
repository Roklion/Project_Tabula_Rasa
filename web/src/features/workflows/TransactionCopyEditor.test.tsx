import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, ApiError, type Schemas } from '../../api/client';
import { ScopeBoundary } from '../../app/ScopeBoundary';
import { session } from '../../test/fixtures';
import { TransactionCopyEditor } from './TransactionCopyEditor';

vi.mock('../concurrency/useReferenceChoices', () => ({
  useReferenceChoices: () => ({ accounts: [{ id: 'cash', name: 'Cash', active: true }],
    categories: [{ id: 'office', name: 'Office', kind: 'Expense' }], payees: [], tags: [], pending: false }),
  activeChoices: (rows: { active: boolean }[]) => rows.filter(row => row.active),
}));

const draft: Schemas['TransactionChanges'] = { txn_date: '2026-10-05', kind: 'Expense', amount: '12.50',
  account_id: 'cash', to_account_id: '', category_id: 'office', payee_id: '', tag_ids: [],
  description: 'Original memo. Copy From source', reference: '', new_payee_name: '', new_tag_name: '' };
const created: Schemas['Transaction'] = { ...draft, tag_ids: draft.tag_ids ?? [], id: 'copy', created_at: 'now', baseline: 'saved-baseline',
  source_type: '', recurring_schedule_id: '' };

function setup() {
  const onClose = vi.fn();
  const router = createMemoryRouter([{ path: '/', element: <ScopeBoundary session={session}>
    <TransactionCopyEditor draft={draft} sourceId="source" onClose={onClose} />
  </ScopeBoundary> }]);
  render(<RouterProvider router={router} />);
  return onClose;
}

beforeEach(() => vi.restoreAllMocks());

it('preserves the failed copy identity and closes the mutation surface after a confirmed save', async () => {
  const create = vi.spyOn(api, 'createTransaction').mockRejectedValueOnce(new ApiError('unavailable')).mockResolvedValue(created);
  const onClose = setup();
  await userEvent.clear(screen.getByLabelText('Amount'));
  await userEvent.type(screen.getByLabelText('Amount'), '25.00');
  await userEvent.click(screen.getByRole('button', { name: 'Save transaction copy' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Your draft is preserved');
  expect(screen.getByLabelText('Amount')).toHaveValue('25.00');
  expect(create).toHaveBeenCalledTimes(1);
  const submitted = create.mock.calls[0][1];
  expect(submitted.copied_from_transaction_id).toBe('source');
  await userEvent.click(screen.getByRole('button', { name: 'Save transaction copy' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Transaction copied.');
  expect(create).toHaveBeenCalledTimes(2);
  expect(create.mock.calls[1][1].transaction_id).toBe(submitted.transaction_id);
  expect(create.mock.calls[1][1].amount).toBe('25.00');
  expect(screen.queryByRole('button', { name: 'Save transaction copy' })).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Amount')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Back to records' }));
  expect(onClose).toHaveBeenCalledOnce();
  expect(create).toHaveBeenCalledTimes(2);
});

it('requires confirmed cancellation for an untouched prefilled copy and keeps the draft when cancelled', async () => {
  const create = vi.spyOn(api, 'createTransaction');
  const onClose = setup();
  await userEvent.click(screen.getByRole('button', { name: 'Back to records' }));
  expect(screen.getByRole('alertdialog', { name: 'Discard draft' })).toBeVisible();
  expect(onClose).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
  expect(screen.getByLabelText('Description / memo')).toHaveValue(draft.description);
  expect(create).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Back to records' }));
  await userEvent.click(screen.getByRole('button', { name: 'Discard draft and close' }));
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  expect(create).not.toHaveBeenCalled();
});
