import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RouterProvider } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, ApiError, type Schemas } from '../../api/client';
import { createTestRouter } from '../../app/router';
import { session } from '../../test/fixtures';

const csv: Schemas['TransactionCsvPreview'] = { columns: ['Date', 'Type', 'Amount', 'Account', 'Category'],
  source_rows: [{ Date: '2026-10-05', Type: 'Expense', Amount: '12.50', Account: 'cash', Category: 'office' }], total_rows: 1, errors: [] };
const qb: Schemas['QuickBooksImportPreview'] = { ...csv, errors: [], conversion_errors: [], duplicate_rows: [3],
  summary: { ready: 1, duplicates: 1, Income: 0, Expense: 1, Transfer: 0, validation_errors: 0, conversion_errors: 0 },
  new_accounts: [{ name: 'Checking', type: 'Bank', classification: 'Asset', opening_balance: '0.00' }],
  new_categories: [{ name: 'Office', kind: 'Expense' }] };
const file = new File(['synthetic source'], 'transactions.csv', { type: 'text/csv' });

beforeEach(() => {
  vi.spyOn(api, 'session').mockResolvedValue(session);
  vi.spyOn(api, 'entities').mockResolvedValue({ items: [session.entity, { id: 'beta', name: 'Beta' }] });
});

it('keeps uploaders independent and performs writes only from explicit import actions', async () => {
  const prepare = vi.spyOn(api, 'prepareTransactionCsv').mockResolvedValue(csv);
  const preview = vi.spyOn(api, 'previewQuickBooksTransactions').mockResolvedValue(qb);
  const importCsv = vi.spyOn(api, 'importTransactionCsv').mockResolvedValue({ status: 'fully_applied', imported_count: 1, transaction_ids: ['created'] });
  const importQb = vi.spyOn(api, 'importQuickBooksTransactions').mockResolvedValue({ status: 'fully_applied', imported_count: 1, transaction_ids: ['qb-created'] });
  render(<RouterProvider router={createTestRouter(['/data'])} />);
  await userEvent.upload(await screen.findByLabelText('Transaction CSV file'), file);
  await screen.findByRole('region', { name: 'Tabula Rasa source rows' });
  await userEvent.upload(screen.getByLabelText('QuickBooks export'), file);
  await screen.findByText(/Already imported or repeated rows will be skipped: 3/);
  expect(prepare).toHaveBeenCalledWith(session, file);
  expect(preview).toHaveBeenCalledWith(session, file, false);
  expect(importCsv).not.toHaveBeenCalled(); expect(importQb).not.toHaveBeenCalled();
  await userEvent.click(screen.getByLabelText('Automatically create missing accounts and categories'));
  await screen.findByText(/Classification: Asset · Type: Bank · Opening balance: 0.00/);
  expect(preview).toHaveBeenLastCalledWith(session, file, true);
  await userEvent.click(screen.getByRole('button', { name: 'Import rows' }));
  await screen.findByText('Imported 1 transactions.');
  expect(importCsv).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('region', { name: 'QuickBooks source rows' })).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: 'Import validated rows' }));
  await waitFor(() => expect(importQb).toHaveBeenCalledWith(session, file, true));
});

it('withholds all uploaders when ordinary write access lacks import permission', async () => {
  vi.mocked(api.session).mockResolvedValue({ ...session, capabilities: ['bookkeeping:read', 'bookkeeping:write'] });
  const prepare = vi.spyOn(api, 'prepareTransactionCsv');
  render(<RouterProvider router={createTestRouter(['/data'])} />);
  expect(await screen.findByText('Importing requires import access to this business (Owner, Admin or Accountant).')).toBeVisible();
  expect(screen.queryByLabelText('Transaction CSV file')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('QuickBooks export')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('QuickBooks mileage CSV')).not.toBeInTheDocument();
  expect(prepare).not.toHaveBeenCalled();
});

it('blocks conversion errors and invalid rows while retaining source diagnostics', async () => {
  const importQb = vi.spyOn(api, 'importQuickBooksTransactions');
  vi.spyOn(api, 'previewQuickBooksTransactions').mockResolvedValue({ ...qb,
    errors: ['QuickBooks row 4: unknown account'], conversion_errors: ['General Ledger row(s) 8: entry count does not balance'],
    summary: { ...qb.summary, validation_errors: 1, conversion_errors: 1 } });
  render(<RouterProvider router={createTestRouter(['/data'])} />);
  await userEvent.upload(await screen.findByLabelText('QuickBooks export'), file);
  expect(await screen.findByText('QuickBooks row 4: unknown account')).toBeVisible();
  expect(screen.getByText('General Ledger row(s) 8: entry count does not balance')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Import validated rows' })).toBeDisabled();
  expect(importQb).not.toHaveBeenCalled();
});

it('retains an uncertain submitted file and prevents automatic or repeated import', async () => {
  vi.spyOn(api, 'prepareTransactionCsv').mockResolvedValue(csv);
  const commit = vi.spyOn(api, 'importTransactionCsv').mockRejectedValue(new ApiError('unavailable'));
  render(<RouterProvider router={createTestRouter(['/data'])} />);
  await userEvent.upload(await screen.findByLabelText('Transaction CSV file'), file);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Import rows' })).toBeEnabled());
  await userEvent.click(screen.getByRole('button', { name: 'Import rows' }));
  expect(await screen.findByText(/Import confirmation is unavailable/)).toBeVisible();
  expect(screen.getByLabelText('Transaction CSV file')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Import rows' })).toBeDisabled();
  expect(screen.getByRole('region', { name: 'Tabula Rasa source rows' })).toBeVisible();
  expect(screen.queryByText('Imported 1 transactions.')).not.toBeInTheDocument();
  expect(commit).toHaveBeenCalledTimes(1);
});

it('ignores a superseded preparation response and blocks business switching during preparation', async () => {
  let complete: (value: Schemas['TransactionCsvPreview']) => void = () => undefined;
  vi.spyOn(api, 'prepareTransactionCsv').mockImplementationOnce(() => new Promise(resolve => { complete = resolve; })).mockResolvedValue(csv);
  render(<RouterProvider router={createTestRouter(['/data'])} />);
  await userEvent.upload(await screen.findByLabelText('Transaction CSV file'), file);
  expect(screen.getByLabelText('Select business')).toBeDisabled();
  const next = new File(['next synthetic source'], 'next.csv', { type: 'text/csv' });
  await userEvent.upload(screen.getByLabelText('Transaction CSV file'), next);
  await screen.findByRole('region', { name: 'Tabula Rasa source rows' });
  complete({ ...csv, source_rows: [{ ...csv.source_rows[0], Account: 'superseded-private-account' }] });
  await waitFor(() => expect(screen.queryByText('superseded-private-account')).not.toBeInTheDocument());
});

it('preserves staged files when navigation is cancelled and clears them on restricted-alpha business switching', async () => {
  vi.spyOn(api, 'prepareTransactionCsv').mockResolvedValue(csv);
  vi.spyOn(api, 'selectEntity').mockResolvedValue({ ...session, entity: { id: 'beta', name: 'Beta' }, cache_scope: 'beta-scope' });
  render(<RouterProvider router={createTestRouter(['/data'])} />);
  await userEvent.upload(await screen.findByLabelText('Transaction CSV file'), file);
  await screen.findByRole('region', { name: 'Tabula Rasa source rows' });
  await userEvent.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('link', { name: 'Transactions' }));
  await userEvent.click(await screen.findByRole('button', { name: 'Keep editing' }));
  expect(screen.getByRole('region', { name: 'Tabula Rasa source rows' })).toBeVisible();
  await userEvent.selectOptions(screen.getByLabelText('Select business'), 'beta');
  await userEvent.click(screen.getByRole('button', { name: 'Discard draft and switch' }));
  await waitFor(() => expect(screen.queryByRole('region', { name: 'Tabula Rasa source rows' })).not.toBeInTheDocument());
  expect(await screen.findByRole('heading', { name: 'Data & backup' })).toBeVisible();
  expect(await screen.findByRole('button', { name: 'Import rows' })).toBeDisabled();
  expect(screen.getByLabelText('Transaction CSV file')).toHaveValue('');
  expect(screen.queryByRole('region', { name: 'Tabula Rasa source rows' })).not.toBeInTheDocument();
});
