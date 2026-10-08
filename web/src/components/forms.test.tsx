import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { createMemoryRouter, Link, RouterProvider } from 'react-router-dom';
import { expect, it } from 'vitest';
import { useLoadedForm } from './useLoadedForm';
import { UnsavedChanges } from './UnsavedChanges';
import { ApiError } from '../api/client';
import { EmptyState, ErrorNotice, Field, LoadingState, SuccessNotice } from './States';

it('keeps immutable load metadata separate from editable values and background reloads', () => {
  const first = { values: { name: 'Loaded' }, metadata: { id: 'account', baseline: 'old' } };
  const { result, rerender } = renderHook(({ loaded }) => useLoadedForm(loaded), { initialProps: { loaded: first } });
  act(() => result.current.form.setValue('name', 'Unsaved draft', { shouldDirty: true }));
  first.metadata.baseline = 'mutated-source';
  const newer = { values: { name: 'Server update' }, metadata: { id: 'account', baseline: 'new' } };
  rerender({ loaded: newer });
  expect(result.current.form.getValues()).toEqual({ name: 'Unsaved draft' });
  expect(result.current.metadata).toEqual({ id: 'account', baseline: 'old' });
  expect(Object.isFrozen(result.current.metadata)).toBe(true);
  act(() => result.current.reload(newer));
  expect(result.current.form.getValues()).toEqual({ name: 'Server update' });
  expect(result.current.metadata.baseline).toBe('new');
  expect(result.current.form.formState.isDirty).toBe(false);
});

it('renders accessible reusable loading, empty, validation, conflict, success and error states', () => {
  render(<><LoadingState /><EmptyState title="No records" /><SuccessNotice>Saved</SuccessNotice>
    <Field id="name" label="Name" error="Required"><input id="name" aria-invalid="true" aria-describedby="name-error" /></Field>
    <ErrorNotice error={new ApiError('validation', 'ref', [{ field: 'name', code: 'invalid', message: 'private server details' }])} />
    <ErrorNotice error={new ApiError('stale')} onReview={() => {}} />
    <ErrorNotice error={new Error('private password')} /></>);
  expect(screen.getByLabelText('Name')).toHaveAccessibleDescription('Required');
  expect(screen.getByRole('button', { name: 'Review latest record' })).toBeVisible();
  expect(screen.getByText('No records')).toBeVisible();
  expect(screen.queryByText(/private/)).not.toBeInTheDocument();
  expect(screen.getAllByRole('status')).toHaveLength(2);
});

it('blocks navigation while dirty and offers explicit keep/discard actions', async () => {
  function Draft() {
    return <><UnsavedChanges dirty /><Link to="/next">Next</Link><input aria-label="Draft" defaultValue="Unsaved" /></>;
  }
  const router = createMemoryRouter([{ path: '/', element: <Draft /> }, { path: '/next', element: <h1>Next page</h1> }]);
  render(<RouterProvider router={router} />);
  fireEvent.click(screen.getByRole('link', { name: 'Next' }));
  expect(await screen.findByRole('alertdialog', { name: 'Unsaved changes' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
  expect(screen.getByRole('textbox', { name: 'Draft' })).toHaveValue('Unsaved');
  fireEvent.click(screen.getByRole('link', { name: 'Next' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Discard draft and leave' }));
  expect(await screen.findByRole('heading', { name: 'Next page' })).toBeVisible();
});
