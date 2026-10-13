import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, ApiError, type Schemas } from '../../api/client';
import { ScopeBoundary } from '../../app/ScopeBoundary';
import { session } from '../../test/fixtures';
import { LedgerBulkActions } from './LedgerBulkActions';

vi.mock('../concurrency/useReferenceChoices', () => ({
  useReferenceChoices: () => ({ accounts: [], categories: [{ id: 'office', name: 'Office', kind: 'Expense' }],
    payees: [{ id: 'vendor', name: 'Vendor', active: true }], tags: [{ id: 'tag', name: 'Job', active: true }], pending: false }),
  activeChoices: (rows: { active: boolean }[]) => rows.filter(row => row.active),
}));

const row: Schemas['Transaction'] = { id: 'one', txn_date: '2026-10-05', kind: 'Expense', amount: '12.50',
  account_id: 'cash', to_account_id: '', category_id: 'office', payee_id: 'vendor', tag_ids: ['tag'],
  description: 'Memo', reference: '', created_at: 'now', baseline: 'original-baseline', source_type: '', recurring_schedule_id: '' };
const ledger: Schemas['LedgerItem'] = { id: 'one', record_id: 'one', entry_type: 'transaction', txn_date: row.txn_date,
  kind: row.kind, amount: row.amount, account: 'Cash', to_account: '', category: 'Office', payee: 'Vendor', tags: ['Job'],
  description: 'Memo', reference: '', receipt_count: 0, postings: [], source_type: '' };

function setup(selected = [ledger], loaded = [row]) {
  const onApplied = vi.fn(); const onCopy = vi.fn();
  const router = createMemoryRouter([{ path: '/', element: <ScopeBoundary session={session}>
    <LedgerBulkActions selected={selected} loaded={loaded} onApplied={onApplied} onCopy={onCopy} />
  </ScopeBoundary> }]);
  render(<RouterProvider router={router} />);
  return { onApplied, onCopy };
}
beforeEach(() => vi.restoreAllMocks());

it('only replaces explicitly selected tags and retains the original loaded baseline', async () => {
  const update = vi.spyOn(api, 'bulkUpdateTransactions').mockResolvedValue({ status: 'fully_applied', count: '1' });
  const { onApplied } = setup();
  expect(screen.getByRole('button', { name: 'Review selected changes' })).toBeDisabled();
  await userEvent.click(screen.getByRole('checkbox', { name: 'Apply Tags to all selected' }));
  await userEvent.deselectOptions(screen.getByLabelText('Tags'), ['tag']);
  await userEvent.click(screen.getByRole('button', { name: 'Review selected changes' }));
  expect(update).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Confirm selected changes' }));
  await waitFor(() => expect(onApplied).toHaveBeenCalledOnce());
  expect(update).toHaveBeenCalledWith(session, { transaction_ids: ['one'], expected: [{ id: 'one', baseline: 'original-baseline' }], changes: { tag_ids: [] } });
});

it('preserves a rejected stale selection without retrying or replacing its baseline', async () => {
  const update = vi.spyOn(api, 'bulkUpdateTransactions').mockRejectedValue(new ApiError('stale'));
  setup();
  await userEvent.selectOptions(screen.getByLabelText('Payee / customer'), '');
  await userEvent.click(screen.getByRole('button', { name: 'Review selected changes' }));
  await userEvent.click(screen.getByRole('button', { name: 'Confirm selected changes' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Your draft is preserved');
  expect(screen.getByLabelText('Payee / customer')).toHaveValue('');
  expect(update).toHaveBeenCalledTimes(1);
  expect(update.mock.calls[0][1].expected[0].baseline).toBe('original-baseline');
});

it('requires acknowledgement and shows the complete count and total before permanent deletion', async () => {
  const remove = vi.spyOn(api, 'bulkDeleteTransactions').mockResolvedValue({ status: 'fully_applied', count: '2' });
  setup([ledger, { ...ledger, id: 'two', record_id: 'two' }], [row, { ...row, id: 'two', amount: '2.50', baseline: 'second-baseline' }]);
  await userEvent.click(screen.getByRole('button', { name: 'Permanently delete selected' }));
  const confirm = screen.getByRole('button', { name: 'Confirm permanent deletion' });
  expect(confirm).toBeDisabled();
  expect(screen.getByRole('alertdialog')).toHaveTextContent('2 transactions with aggregate absolute amount 15.00');
  await userEvent.click(screen.getByRole('checkbox', { name: 'I understand that this cannot be undone.' }));
  await userEvent.click(confirm);
  await waitFor(() => expect(remove).toHaveBeenCalledOnce());
  expect(remove.mock.calls[0][1].transaction_ids).toEqual(['one', 'two']);
});

it('blocks the whole journal/projection selection and only copies exactly one ordinary record', async () => {
  const prepare = vi.spyOn(api, 'prepareTransactionCopy').mockResolvedValue({ txn_date: row.txn_date, kind: row.kind,
    amount: row.amount, account_id: row.account_id, to_account_id: '', category_id: row.category_id,
    payee_id: '', tag_ids: [], description: 'Memo. Copy From one', reference: '', new_payee_name: '', new_tag_name: '' });
  const { onCopy } = setup();
  await userEvent.click(screen.getByRole('button', { name: 'Copy transaction' }));
  await waitFor(() => expect(onCopy).toHaveBeenCalledOnce());
  expect(prepare).toHaveBeenCalledWith(session, 'one', 'original-baseline');
});

it.each(['journal', 'mixed_use_expense', 'depreciation'])('never mutates the ordinary subset when selection includes %s', async protectedKind => {
  const update = vi.spyOn(api, 'bulkUpdateTransactions');
  const remove = vi.spyOn(api, 'bulkDeleteTransactions');
  setup([ledger, { ...ledger, id: 'protected', record_id: 'protected',
    entry_type: protectedKind === 'journal' ? 'journal' : 'transaction', source_type: protectedKind === 'journal' ? '' : protectedKind }]);
  expect(screen.getByRole('button', { name: 'Permanently delete selected' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Copy transaction' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Review selected changes' })).toBeDisabled();
  expect(update).not.toHaveBeenCalled(); expect(remove).not.toHaveBeenCalled();
});
