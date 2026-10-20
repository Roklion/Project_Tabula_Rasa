import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ScopeBoundary } from '../app/ScopeBoundary';
import { session } from '../test/fixtures';
import { FilterPanel } from './FilterPanel';

beforeEach(() => sessionStorage.clear());
const panel = <FilterPanel name="ledger" title="Filter ledger" label="Ledger filters" summary="Type: Expense"><input aria-label="Search" defaultValue="Office" /></FilterPanel>;

it('keeps mounted values when collapsed and remembers only scoped presentation across navigation', () => {
  const view = render(<ScopeBoundary session={session}>{panel}</ScopeBoundary>);
  const toggle = screen.getByRole('button', { name: /Filter ledger/ });
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  expect(screen.getByLabelText('Search')).not.toBeVisible();
  expect(screen.getByLabelText('Search')).toHaveValue('Office');
  expect(screen.getByText('Type: Expense')).toBeVisible();
  view.unmount();
  const next = render(<ScopeBoundary session={session}>{panel}</ScopeBoundary>);
  expect(screen.getByRole('button', { name: /Show filters/ })).toHaveAttribute('aria-expanded', 'false');
  next.rerender(<ScopeBoundary session={{ ...session, entity: { id: 'beta', name: 'Beta' } }}>{panel}</ScopeBoundary>);
  expect(screen.getByLabelText('Search')).toBeVisible();
  expect(screen.getByRole('button', { name: /Hide filters/ })).toHaveAttribute('aria-expanded', 'true');
});

it('keeps panel states separate per page and works when optional storage is unavailable', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
  const view = render(<ScopeBoundary session={session}>{panel}</ScopeBoundary>);
  fireEvent.click(screen.getByRole('button', { name: /Hide filters/ }));
  expect(screen.getByLabelText('Search')).not.toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: /Show filters/ }));
  expect(screen.getByLabelText('Search')).toBeVisible();
  view.unmount();
  vi.restoreAllMocks();
  const first = render(<ScopeBoundary session={session}>{panel}</ScopeBoundary>);
  fireEvent.click(screen.getByRole('button', { name: /Hide filters/ }));
  first.unmount();
  render(<ScopeBoundary session={session}><FilterPanel name="mileage" title="Mileage filters" label="Mileage filters" summary="All trips">Mileage controls</FilterPanel></ScopeBoundary>);
  expect(screen.getByText('Mileage controls')).toBeVisible();
});
