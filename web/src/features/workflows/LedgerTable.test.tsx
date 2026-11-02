import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { type Schemas } from '../../api/client';
import { EntityContext } from '../../app/context';
import { session } from '../../test/fixtures';
import { LedgerTable } from './LedgerTable';

const ordinary: Schemas['LedgerItem'] = {
  id: 'ordinary', record_id: 'ordinary', entry_type: 'transaction', txn_date: '2026-10-01', kind: 'Expense',
  amount: '12.50', account: 'Cash', to_account: '', category: 'Office', payee: '', tags: [],
  description: 'Recurring monthly expense', reference: '', receipt_count: 0, source_type: '', recurring_schedule_id: '', postings: [],
};

it('adds durable recurring badges while preserving accounting type and source-owned actions', async () => {
  const edit = vi.fn().mockResolvedValue(undefined);
  const recurring = { ...ordinary, id: 'initial', record_id: 'initial', description: 'Edited memo', recurring_schedule_id: 'schedule' };
  const generated = { ...recurring, id: 'generated', record_id: 'generated' };
  const mixed = { ...recurring, id: 'mixed', record_id: 'mixed', source_type: 'mixed_use_expense' };
  render(<MemoryRouter><EntityContext.Provider value={session}><LedgerTable
    rows={[ordinary, recurring, generated, mixed, { ...mixed, id: 'plain-mixed', recurring_schedule_id: '' }]}
    filters={{ kind: 'All' }} edit={edit} loadingRecord={false} />
  </EntityContext.Provider></MemoryRouter>);
  expect(screen.getByRole('columnheader', { name: 'Type' })).toBeVisible();
  expect(screen.getAllByText('Recurring', { exact: true })).toHaveLength(3);
  expect(screen.getAllByRole('rowheader', { name: 'Expense · Recurring' })).toHaveLength(2);
  const mixedRow = screen.getByRole('rowheader', { name: 'Expense · Mixed-use · Recurring' }).closest('tr')!;
  expect(within(mixedRow).getAllByText(/^(Expense|Mixed-use|Recurring)$/)).toHaveLength(3);
  expect(within(mixedRow).getByRole('link', { name: 'Manage mixed-use expense' })).toHaveAttribute('href', '/mixed-use');
  expect(within(mixedRow).queryByRole('button', { name: /^Edit / })).not.toBeInTheDocument();
  expect(screen.getByRole('rowheader', { name: 'Expense' })).toBeVisible();
  expect(screen.getByRole('rowheader', { name: 'Expense · Mixed-use' })).toBeVisible();
  await userEvent.click(screen.getAllByRole('button', { name: 'Edit 2026-10-01 · Edited memo · 12.50' })[0]);
  expect(edit).toHaveBeenCalledWith(recurring);
});
