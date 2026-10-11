import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { ActionButton, PageHeader, SectionHeader, TableRegion } from './VisualPrimitives';

it('preserves native button semantics and prevents disabled and pending actions', () => {
  const submit = vi.fn(event => event.preventDefault());
  const action = vi.fn();
  render(<form onSubmit={submit}>
    <ActionButton onClick={action}>Review</ActionButton>
    <ActionButton tone="primary" type="submit">Save account</ActionButton>
    <ActionButton tone="destructive" disabled onClick={action}>Delete</ActionButton>
    <ActionButton tone="primary" pending onClick={action}>Save pending</ActionButton>
  </form>);
  fireEvent.click(screen.getByRole('button', { name: 'Review' }));
  expect(action).toHaveBeenCalledTimes(1);
  expect(submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Save account' }));
  expect(submit).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save pending' }));
  expect(action).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Save pending' })).toHaveAttribute('aria-busy', 'true');
});

it('keeps heading levels, navigation links and table semantics accessible', () => {
  render(<><PageHeader title="Accounts" description="Selected business" actions={<a href="/accounts/new">Add account</a>} />
    <SectionHeader title="Business accounts" description="All accounts" />
    <TableRegion label="Accounts"><table><caption>Account balances</caption><tbody><tr>
      <th scope="row">Bank</th><td>0.00</td></tr></tbody></table></TableRegion></>);
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Accounts');
  expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Business accounts');
  expect(screen.getByRole('link', { name: 'Add account' })).toHaveAttribute('href', '/accounts/new');
  expect(screen.getByRole('region', { name: 'Accounts' })).toHaveAttribute('tabindex', '0');
  expect(screen.getByRole('rowheader', { name: 'Bank' })).toBeVisible();
});
