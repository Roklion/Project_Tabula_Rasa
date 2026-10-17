import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../../api/client';
import { ScopeBoundary } from '../../app/ScopeBoundary';
import { session } from '../../test/fixtures';
import { RecurringPage } from './RecurringPage';

afterEach(() => vi.restoreAllMocks());

it.each([0, 2])('reports %i queued schedules without claiming synchronous generation', async count => {
  vi.spyOn(api, 'recurring').mockResolvedValue({ items: [] });
  const reconcile = vi.spyOn(api, 'reconcileRecurring').mockResolvedValue({
    generated_count: 0, attention_count: 0, queued_count: count, execution_mode: 'worker',
  });
  render(<MemoryRouter><ScopeBoundary session={session}><RecurringPage /></ScopeBoundary></MemoryRouter>);
  await userEvent.click(screen.getByRole('button', { name: 'Generate due occurrences' }));
  expect(reconcile).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Confirm generation' }));
  expect(await screen.findByText(new RegExp(`Queued ${count} schedule`))).toHaveTextContent('refresh later to inspect occurrences and attention');
  expect(screen.queryByText(/Generated 0 occurrence/)).not.toBeInTheDocument();
  expect(reconcile).toHaveBeenCalledTimes(1);
});
