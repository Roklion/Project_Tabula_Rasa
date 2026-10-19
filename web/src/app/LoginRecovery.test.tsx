import { render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import { ContextBoundary } from './ContextBoundary';

afterEach(() => { window.history.replaceState(null, '', '/'); vi.restoreAllMocks(); });

it.each([
  ['login_freshness', 'The provider session did not confirm a recent sign-in. Please authenticate again.'],
  ['login_transaction', 'This sign-in attempt expired, was already used, or could not be matched to this browser.'],
  ['provider_authorization', 'The sign-in provider did not complete authentication.'],
  ['userinfo_validation', 'Your verified account details could not be confirmed with the sign-in provider.'],
])('explains %s and offers a deliberate fresh login without mounting private data', (category, message) => {
  const session = vi.spyOn(api, 'session');
  window.history.replaceState(null, '', '/signed-out?reason=login_failed&category=' + category + '&reference=' + 'a'.repeat(32));
  render(<ContextBoundary><p>Private ledger</p></ContextBoundary>);
  expect(screen.getByText(message)).toBeVisible();
  expect(screen.getByText('a'.repeat(32))).toBeVisible();
  expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/api/v1/auth/login');
  expect(screen.getByText(/You do not need to delete browser cookies/)).toBeVisible();
  expect(screen.queryByText('Private ledger')).not.toBeInTheDocument();
  expect(session).not.toHaveBeenCalled();
});

it('keeps provider failure details and arbitrary query values out of the screen', () => {
  window.history.replaceState(null, '', '/signed-out?reason=login_failed&category=private-provider-error&reference=private-token&error_description=private-description');
  render(<ContextBoundary><p>Private ledger</p></ContextBoundary>);
  expect(screen.getByText('Sign-in did not complete.')).toBeVisible();
  expect(document.body.textContent).not.toMatch(/private-provider|private-token|private-description/);
});

it('distinguishes an unavailable provider from an ordinary signed-out visit', () => {
  window.history.replaceState(null, '', '/signed-out?reason=unavailable&category=token_exchange');
  const view = render(<ContextBoundary><p>Private ledger</p></ContextBoundary>);
  expect(screen.getByRole('alert')).toHaveTextContent('The sign-in service is temporarily unavailable.');
  view.unmount();
  window.history.replaceState(null, '', '/signed-out');
  render(<ContextBoundary><p>Private ledger</p></ContextBoundary>);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Sign in' })).toBeVisible();
});
