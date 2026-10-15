import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError, type ErrorCode } from '../../api/client';
import { session } from '../../test/fixtures';
import { ScopeBoundary } from '../../app/ScopeBoundary';
import { WorkspacePage } from './WorkspacePage';
import { InvitationAcceptance } from './InvitationAcceptance';

afterEach(() => vi.restoreAllMocks());

it.each([
  ['reauthentication_required', 'Sign in again to continue. Re-enter any invitation credential after login.'],
  ['invitation_used', 'This invitation was already redeemed, declined or revoked. Ask your administrator for a new one.'],
  ['invitation_expired', 'This invitation expired. Ask your administrator for a new one.'],
  ['invitation_invalid', 'This invitation is unavailable for this account. Check the invited email with your administrator.'],
])('clears the submitted invitation credential and explains %s', async (code, message) => {
  const respond = vi.spyOn(api, 'respondInvitation').mockRejectedValue(new ApiError(code as ErrorCode));
  render(<InvitationAcceptance session={session} />);
  fireEvent.change(screen.getByLabelText('Invitation credential'), { target: { value: 'synthetic-credential' } });
  fireEvent.click(screen.getByRole('button', { name: 'Accept invitation' }));
  expect(await screen.findByText(message)).toBeVisible();
  expect(screen.getByLabelText('Invitation credential')).toHaveValue('');
  expect(respond).toHaveBeenCalledWith(session, 'synthetic-credential', true);
  if (code === 'reauthentication_required') expect(screen.getByRole('link', { name: 'Sign in again' })).toBeVisible();
});

it('allows an authenticated decline without retaining the credential', async () => {
  vi.spyOn(api, 'respondInvitation').mockResolvedValue({ state: 'declined' });
  render(<InvitationAcceptance session={session} />);
  fireEvent.change(screen.getByLabelText('Invitation credential'), { target: { value: 'synthetic-credential' } });
  fireEvent.click(screen.getByRole('button', { name: 'Decline invitation' }));
  expect(await screen.findByText('Invitation declined.')).toBeVisible();
  expect(screen.getByLabelText('Invitation credential')).toHaveValue('');
});

it('read-only workspace UI offers invitation acceptance without fetching administration', () => {
  const members = vi.spyOn(api, 'members');
  const invitations = vi.spyOn(api, 'invitations');
  render(<ScopeBoundary session={{ ...session, trusted_development: false, capabilities: ['bookkeeping:read'] }}><WorkspacePage /></ScopeBoundary>);
  expect(screen.getByText('Workspace administration requires Owner or Admin access.')).toBeVisible();
  expect(screen.getByLabelText('Invitation credential')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Create invitation' })).not.toBeInTheDocument();
  expect(members).not.toHaveBeenCalled();
  expect(invitations).not.toHaveBeenCalled();
});

it('refreshes invitation state after an uncertain create without exposing or retrying the credential', async () => {
  vi.spyOn(api, 'members').mockResolvedValue({ items: [] });
  vi.spyOn(api, 'invitations').mockResolvedValueOnce({ items: [] }).mockResolvedValue({ items: [{
    id: 'issued', recipient_email: 'recipient@example.test', role: 'read_only', state: 'pending', expires_at: '2026-10-15T12:00:00Z',
  }] });
  const invite = vi.spyOn(api, 'invite').mockRejectedValue(new ApiError('unavailable'));
  render(<ScopeBoundary session={{ ...session, trusted_development: false, capabilities: ['bookkeeping:read', 'members:manage'] }}><WorkspacePage /></ScopeBoundary>);
  await screen.findByText('No invitations.');
  fireEvent.change(screen.getByLabelText('Recipient email'), { target: { value: 'recipient@example.test' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create invitation' }));
  expect(await screen.findByRole('alert')).toBeVisible();
  expect(await screen.findByText(/recipient@example.test.*pending/)).toBeVisible();
  expect(screen.queryByLabelText('New invitation credential')).not.toBeInTheDocument();
  expect(invite).toHaveBeenCalledTimes(1);
});
