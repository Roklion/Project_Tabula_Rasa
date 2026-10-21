import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError, type SessionState } from '../../api/client';
import { session } from '../../test/fixtures';
import { BusinessesPage } from './BusinessesPage';
import { ScopeBoundary } from '../../app/ScopeBoundary';
import { EntitySelectionContext } from '../../app/entitySelectionContext';
import { LedgerSetup, Onboarding } from './Onboarding';
import { ContextBoundary } from '../../app/ContextBoundary';
import { InvitationAcceptance } from './InvitationAcceptance';

const setup: SessionState = { state: 'needs_setup', actor_id: 'new-user', organization_id: null,
  entity: null, capabilities: [], cache_scope: 'setup', csrf_token: 'csrf', trusted_development: false };
afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); window.history.replaceState({}, '', '/'); });

async function review() {
  await screen.findByLabelText('Business name');
  expect(screen.queryByLabelText('Workspace name')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Business name'), { target: { value: 'Business' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review defaults' }));
}

it('separates fresh books, invitations and operator migration without automatic creation', async () => {
  const create = vi.spyOn(api, 'createBusiness');
  const view = render(<Onboarding session={setup} />);
  fireEvent.click(screen.getByRole('button', { name: 'Move existing Sheets books' }));
  expect(screen.getByText(/explicit migration and cutover/)).toBeVisible();
  expect(create).not.toHaveBeenCalled();
  view.unmount();
  window.history.replaceState({}, '', '/invitations');
  render(<Onboarding session={setup} />);
  expect(screen.getByLabelText('Invitation credential')).toBeVisible();
  expect(screen.queryByLabelText('Business name')).not.toBeInTheDocument();
});

it('preserves names on Back, validates whitespace, and reuses the exact request on explicit retry', async () => {
  const create = vi.spyOn(api, 'createBusiness').mockRejectedValue(new ApiError('unavailable'));
  vi.spyOn(api, 'bootstrapStatus').mockResolvedValue({ state: 'not_started' });
  render(<LedgerSetup session={setup} />);
  await review();
  fireEvent.click(screen.getByRole('button', { name: 'Back' }));
  expect(screen.getByLabelText('Business name')).toHaveValue('Business');
  fireEvent.change(screen.getByLabelText('Business name'), { target: { value: '   ' } });
  expect(screen.getByRole('button', { name: 'Review defaults' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Business name'), { target: { value: 'Business' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review defaults' }));
  fireEvent.click(screen.getByRole('button', { name: 'Create business' }));
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Retry same setup' }));
  await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
  expect(create.mock.calls[0][1]).toEqual(create.mock.calls[1][1]);
  expect(sessionStorage.length).toBe(1);
  expect(sessionStorage.getItem(sessionStorage.key(0)!)).toBe(create.mock.calls[0][1].request_id);
  expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument();
});

it('resumes only the authenticated actor receipt after refresh and never restores private names', async () => {
  sessionStorage.setItem('tabula-setup:new-user:first', 'original-request-id');
  sessionStorage.setItem('tabula-setup:other-user:first', 'foreign-request-id');
  const status = vi.spyOn(api, 'bootstrapStatus').mockResolvedValue({ state: 'not_started' });
  render(<LedgerSetup session={setup} />);
  expect(await screen.findByText(/Setup was interrupted/)).toBeVisible();
  expect(status).toHaveBeenCalledWith('original-request-id', expect.any(AbortSignal));
  expect(screen.getByLabelText('Business name')).toHaveValue('');
});

it('uses a bounded readback after lost response, then selects only through authorized API', async () => {
  vi.spyOn(api, 'createBusiness').mockRejectedValue(new ApiError('unavailable'));
  const status = vi.spyOn(api, 'bootstrapStatus').mockResolvedValue({ state: 'ready', entity_id: 'created' });
  vi.spyOn(api, 'session').mockResolvedValue({ ...session, actor_id: setup.actor_id, trusted_development: false });
  const select = vi.spyOn(api, 'selectEntity').mockRejectedValue(new ApiError('forbidden'));
  render(<LedgerSetup session={setup} />);
  await review(); fireEvent.click(screen.getByRole('button', { name: 'Create business' }));
  await screen.findByRole('alert');
  expect(status).toHaveBeenCalledTimes(1);
  expect(select).toHaveBeenCalledWith(expect.objectContaining({ actor_id: setup.actor_id }), 'created');
  expect(sessionStorage.length).toBe(1);
});

it('does not create if the receipt cannot be stored', async () => {
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
  const create = vi.spyOn(api, 'createBusiness');
  render(<LedgerSetup session={setup} />);
  await review(); fireEvent.click(screen.getByRole('button', { name: 'Create business' }));
  await screen.findByRole('alert'); expect(create).not.toHaveBeenCalled();
});

it('does not reinterpret a rejected request as uncertain success', async () => {
  vi.spyOn(api, 'createBusiness').mockRejectedValue(new ApiError('conflict'));
  const status = vi.spyOn(api, 'bootstrapStatus');
  render(<LedgerSetup session={setup} />);
  await review(); fireEvent.click(screen.getByRole('button', { name: 'Create business' }));
  await screen.findByRole('alert');
  expect(status).not.toHaveBeenCalled();
});

it('returns invitees to acceptance after required reauthentication and clears the credential', async () => {
  vi.spyOn(api, 'respondInvitation').mockRejectedValue(new ApiError('reauthentication_required'));
  render(<InvitationAcceptance session={setup} />);
  fireEvent.change(screen.getByLabelText('Invitation credential'), { target: { value: 'private-credential' } });
  fireEvent.click(screen.getByRole('button', { name: 'Accept invitation' }));
  expect(await screen.findByRole('link', { name: 'Sign in again' })).toHaveAttribute('href', '/api/v1/auth/login?return_path=/invitations');
  expect(screen.getByLabelText('Invitation credential')).toHaveValue('');
});

it('routes an existing invited member to acceptance and preserves that route through login', async () => {
  window.history.replaceState({}, '', '/invitations');
  vi.spyOn(api, 'session').mockRejectedValueOnce(new ApiError('unauthorized')).mockResolvedValue({ ...session, trusted_development: false });
  vi.spyOn(api, 'entities').mockResolvedValue({ items: [session.entity] });
  const first = render(<ContextBoundary><p>Private dashboard</p></ContextBoundary>);
  expect(await screen.findByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/api/v1/auth/login?return_path=/invitations');
  first.unmount();
  render(<ContextBoundary><p>Private dashboard</p></ContextBoundary>);
  expect(await screen.findByLabelText('Invitation credential')).toBeVisible();
  expect(screen.queryByText('Private dashboard')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Create your first business' })).not.toBeInTheDocument();
});


it('offers independent business creation to an existing read-only member and lists current access', async () => {
  const member = { ...session, trusted_development: false, capabilities: ['bookkeeping:read'] };
  const select = vi.fn();
  render(<ScopeBoundary session={member}><EntitySelectionContext.Provider value={{ pending: false, select,
    items: [{ ...member.entity, role: 'read_only' }, { id: 'other', name: 'Other business', role: 'owner' }] }}>
    <BusinessesPage /></EntitySelectionContext.Provider></ScopeBoundary>);
  expect(screen.getByRole('heading', { name: 'My Businesses' })).toBeVisible();
  expect(screen.getByText('read only')).toBeVisible();
  expect(screen.getByText('Other business')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Create another business' }));
  await review();
  expect(screen.queryByText(/Workspace:/)).not.toBeInTheDocument();
});

it('keeps creation pending and submits a business-only payload once', async () => {
  let reject!: (error: unknown) => void;
  const create = vi.spyOn(api, 'createBusiness').mockImplementation(() => new Promise((_, no) => { reject = no; }));
  render(<LedgerSetup session={setup} />);
  await review();
  const submit = screen.getByRole('button', { name: 'Create business' });
  fireEvent.click(submit); fireEvent.click(submit);
  expect(submit).toBeDisabled();
  expect(await screen.findByText('Creating your ledger and selecting the business…')).toBeVisible();
  expect(create).toHaveBeenCalledTimes(1);
  expect(create.mock.calls[0][1]).toEqual({ request_id: expect.any(String), business_name: 'Business' });
  reject(new ApiError('validation'));
  expect(await screen.findByRole('alert')).toBeVisible();
});


it('retries selection of a confirmed refreshed receipt without submitting creation again', async () => {
  sessionStorage.setItem('tabula-setup:new-user:first', 'original-request-id');
  vi.spyOn(api, 'bootstrapStatus').mockResolvedValue({ state: 'ready', entity_id: 'created' });
  vi.spyOn(api, 'session').mockResolvedValue({ ...session, actor_id: setup.actor_id, trusted_development: false });
  const select = vi.spyOn(api, 'selectEntity').mockRejectedValue(new ApiError('forbidden'));
  const create = vi.spyOn(api, 'createBusiness');
  render(<LedgerSetup session={setup} />);
  await screen.findByRole('alert');
  expect(screen.getByText('Your business was created. Retry to open its ledger.')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Retry same setup' }));
  await waitFor(() => expect(select).toHaveBeenCalledTimes(2));
  expect(create).not.toHaveBeenCalled();
  expect(sessionStorage.getItem('tabula-setup:new-user:first')).toBe('original-request-id');
});
