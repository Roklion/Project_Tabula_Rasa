import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { EntitySelector } from './EntitySelection';
import { EntitySelectionContext } from './entitySelectionContext';
import { ScopeBoundary } from './ScopeBoundary';
import { session } from '../test/fixtures';

it('distinguishes same-name businesses by full stable reference and confirms the target', async () => {
  const select = vi.fn().mockResolvedValue(undefined);
  const first = { currency_code: 'USD' as const, id: 'identical-prefix-first', name: 'Shared business', role: 'owner' as const };
  const second = { currency_code: 'CAD' as const, id: 'identical-prefix-second', name: 'Shared business', role: 'owner' as const };
  render(<ScopeBoundary session={session}><EntitySelectionContext.Provider value={{ pending: false, select, items: [first, second] }}>
    <EntitySelector activeId={first.id} />
  </EntitySelectionContext.Provider></ScopeBoundary>);
  expect(screen.getByRole('option', { name: `Shared business (reference: ${first.id}) · USD · Owner` })).toBeVisible();
  expect(screen.getByRole('option', { name: `Shared business (reference: ${second.id}) · CAD · Owner` })).toBeVisible();
  fireEvent.change(screen.getByLabelText('Select business'), { target: { value: second.id } });
  expect(screen.getByText(`Business reference: ${second.id}`)).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Discard draft and switch' }));
  await waitFor(() => expect(select).toHaveBeenCalledExactlyOnceWith(second.id));
});

it('keeps unique business names concise and cancellation preserves the current ledger', () => {
  const select = vi.fn();
  render(<ScopeBoundary session={session}><EntitySelectionContext.Provider value={{ pending: false, select,
    items: [{ currency_code: 'USD' as const, id: 'a', name: 'One' }, { currency_code: 'USD' as const, id: 'b', name: 'Two' }] }}>
    <EntitySelector activeId="a" />
  </EntitySelectionContext.Provider></ScopeBoundary>);
  expect(screen.getByRole('option', { name: 'One · USD' })).toBeVisible();
  fireEvent.change(screen.getByLabelText('Select business'), { target: { value: 'b' } });
  fireEvent.click(screen.getByRole('button', { name: 'Keep current business' }));
  expect(select).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Select business')).toHaveValue('a');
});
