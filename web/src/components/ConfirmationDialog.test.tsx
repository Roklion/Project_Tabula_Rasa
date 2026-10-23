import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { ConfirmationDialog } from './ConfirmationDialog';

it('starts Tab at either end when focus is on the dialog rather than a control', () => {
  render(<ConfirmationDialog title="Review" keepLabel="Keep" confirmLabel="Confirm" onKeep={vi.fn()} onConfirm={vi.fn()}>
    <a href="/reauthenticate">Sign in again</a>
  </ConfirmationDialog>);
  const dialog = screen.getByRole('alertdialog');
  dialog.setAttribute('tabindex', '-1');
  dialog.focus();
  fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true });
  expect(screen.getByRole('button', { name: 'Confirm' })).toHaveFocus();
  dialog.focus();
  fireEvent.keyDown(dialog, { key: 'Tab' });
  expect(screen.getByRole('link', { name: 'Sign in again' })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: 'Tab', shiftKey: true });
  expect(screen.getByRole('button', { name: 'Confirm' })).toHaveFocus();
});
