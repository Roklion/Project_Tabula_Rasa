import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type SessionState, type Schemas } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { ErrorNotice, Field, LoadingState, SuccessNotice } from '../../components/States';
import { ActionButton, FormSection, PageHeader } from '../../components/VisualPrimitives';
import { ConfirmationDialog } from '../../components/ConfirmationDialog';

const roleNames = { owner: 'Owner', admin: 'Admin', editor: 'Editor', accountant: 'Accountant', read_only: 'Read-only' };
type Role = keyof typeof roleNames;

export function InvitationAcceptance({ session }: { session: SessionState }) {
  const [credential, setCredential] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [declined, setDeclined] = useState(false);
  async function respond(accept: boolean) {
    const submitted = credential;
    setCredential(''); setPending(true); setError(undefined);
    try {
      await api.respondInvitation(session, submitted, accept);
      if (accept) window.location.replace('/');
      else setDeclined(true);
    } catch (failure) { setError(failure); }
    finally { setPending(false); }
  }
  return <section className="surface"><h2>Respond to an invitation</h2>
    <p>Sign in with the invited account, then paste the credential shared privately by your workspace administrator. A recent sign-in is required.</p>
    <form onSubmit={event => { event.preventDefault(); void respond(true); }}>
      <Field id="invitation-credential" label="Invitation credential"><input id="invitation-credential" type="password" autoComplete="off" spellCheck={false}
        value={credential} onChange={event => setCredential(event.target.value)} required disabled={pending} /></Field>
      <div className="actions"><ActionButton type="submit" disabled={!credential || pending}>Accept invitation</ActionButton>
        <ActionButton type="button" disabled={!credential || pending} onClick={() => void respond(false)}>Decline invitation</ActionButton></div>
    </form>
    {declined && <SuccessNotice>Invitation declined.</SuccessNotice>}
    {error !== undefined && <ErrorNotice error={error} />}
  </section>;
}

function MemberEditor({ member, owner, onSave, onGrant }: { member: Schemas['Member']; owner: boolean; onSave: (role: Role, active: boolean) => Promise<void>; onGrant: () => Promise<void> }) {
  const actor = useEntity().actor_id;
  const [role, setRole] = useState<Role>(member.role);
  const [active, setActive] = useState(member.state === 'active');
  const [confirm, setConfirm] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [grant, setGrant] = useState(false);
  const allowed = owner || member.role === 'admin' && member.user_id === actor || !['owner', 'admin'].includes(member.role);
  return <section className="surface"><h3>{member.display_name || 'Workspace member'}</h3>
    <p>Current role: {roleNames[member.role]} · {member.state}</p>
    {allowed && <><Field id={'role-' + member.user_id} label="Member role"><select id={'role-' + member.user_id} value={role} disabled={pending}
      onChange={event => setRole(event.target.value as Role)}>
      {(Object.keys(roleNames) as Role[]).filter(item => item === 'owner' ? member.role === 'owner' : owner || item !== 'admin' || member.role === 'admin').map(item => <option key={item} value={item}>{roleNames[item]}</option>)}
    </select></Field>
    <label><input type="checkbox" checked={active} disabled={pending} onChange={event => setActive(event.target.checked)} /> Active membership</label>
    <div className="actions"><ActionButton disabled={pending} onClick={() => setConfirm(true)}>Review membership change</ActionButton></div></>}
    {owner && (member.role !== 'owner' || member.state !== 'active') && <ActionButton disabled={pending} onClick={() => setGrant(true)}>Grant ownership</ActionButton>}
    {grant && <ConfirmationDialog title="Grant ownership" keepLabel="Keep current role" confirmLabel="Confirm ownership grant" pending={pending} onKeep={() => setGrant(false)}
      onConfirm={() => { setPending(true); setError(undefined); void onGrant().then(() => setGrant(false)).catch(setError).finally(() => setPending(false)); }}>
      Give this member full Owner authority, including business administration and recovery approval?
      {error !== undefined && <ErrorNotice error={error} />}
    </ConfirmationDialog>}
    {confirm && <ConfirmationDialog title="Change membership" keepLabel="Keep current membership" confirmLabel="Confirm membership change" pending={pending} onKeep={() => setConfirm(false)}
      onConfirm={() => { setPending(true); setError(undefined); void onSave(role, active).then(() => setConfirm(false)).catch(setError).finally(() => setPending(false)); }}>
      Set this member to {roleNames[role]} and {active ? 'active' : 'inactive'}? Access changes on their next request. A workspace must retain an active Owner.
      {error !== undefined && <ErrorNotice error={error} />}
    </ConfirmationDialog>}
    {error !== undefined && !confirm && !grant && <ErrorNotice error={error} />}
  </section>;
}

function MemberAdministration() {
  const session = useEntity();
  const cache = useQueryClient();
  const owner = session.capabilities.includes('ownership:manage');
  const key = resourceKey(session, 'members');
  const invitationKey = resourceKey(session, 'invitations');
  const members = useQuery({ queryKey: key, queryFn: ({ signal }) => api.members(session, signal) });
  const invitations = useQuery({ queryKey: invitationKey, queryFn: ({ signal }) => api.invitations(session, signal) });
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Schemas['InviteRequest']['role']>('read_only');
  const [issued, setIssued] = useState<string>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  async function invite() {
    setIssued(undefined); setError(undefined); setPending(true);
    try {
      const result = await api.invite(session, { email, role });
      setIssued(result.credential); setEmail('');
    } catch (failure) { setError(failure); }
    finally { await cache.invalidateQueries({ queryKey: invitationKey }); setPending(false); }
  }
  return <><form className="surface" onSubmit={event => { event.preventDefault(); void invite(); }}>
    <FormSection title="Invite a collaborator"><Field id="invite-email" label="Recipient email"><input id="invite-email" type="email" value={email} required maxLength={320} disabled={pending} onChange={event => setEmail(event.target.value)} /></Field>
      <Field id="invite-role" label="Invitation role"><select id="invite-role" value={role} disabled={pending} onChange={event => setRole(event.target.value as typeof role)}>
        {(['admin', 'editor', 'accountant', 'read_only'] as const).filter(item => owner || item !== 'admin').map(item => <option key={item} value={item}>{roleNames[item]}</option>)}
      </select></Field></FormSection>
    <p>Share the credential privately with the intended recipient. It expires after 48 hours and can be used once.</p>
    <div className="actions"><ActionButton type="submit" disabled={pending}>Create invitation</ActionButton></div>
  </form>
  {issued && <section className="notice neutral"><h2>Share this credential once</h2><p>This value disappears when you leave this workspace or dismiss it.</p>
    <Field id="issued-invitation" label="New invitation credential"><input id="issued-invitation" readOnly value={issued} autoComplete="off" spellCheck={false} /></Field>
    <ActionButton onClick={() => setIssued(undefined)}>Dismiss credential</ActionButton></section>}
  {error !== undefined && <ErrorNotice error={error} />}
  <h2>Members</h2>
  {members.isPending && <LoadingState />}{members.error && <ErrorNotice error={members.error} operation="read" />}
  {members.data?.items.map(member => <MemberEditor key={member.user_id + ':' + member.authorization_version} member={member} owner={owner} onSave={async (role, active) => {
    try {
      await api.changeMember(session, member.user_id, { role, active, authorization_version: member.authorization_version });
      window.dispatchEvent(new Event('tabula:identity-check'));
    } finally { await cache.invalidateQueries({ queryKey: key }); }
  }} onGrant={async () => {
    try { await api.grantOwnership(session, member.user_id, member.authorization_version); }
    finally { await cache.invalidateQueries({ queryKey: key }); }
  }} />)}
  <h2>Invitations</h2>
  {invitations.error && <ErrorNotice error={invitations.error} operation="read" />}
  {invitations.data?.items.length === 0 && <p>No invitations.</p>}
  {invitations.data?.items.map(item => <section className="surface" key={item.id}><p>{item.recipient_email} · {roleNames[item.role]} · {item.state} · expires {new Date(item.expires_at).toLocaleString()}</p>
    {item.state === 'pending' && (owner || item.role !== 'admin') && <ActionButton disabled={pending} onClick={() => {
      setPending(true); setError(undefined); void api.revokeInvitation(session, item.id).catch(setError).finally(async () => { await cache.invalidateQueries({ queryKey: invitationKey }); setPending(false); });
    }}>Revoke invitation</ActionButton>}</section>)}
  </>;
}

export function WorkspacePage() {
  const session = useEntity();
  return <><PageHeader title="Workspace & members" description={session.entity.organization_name ?? 'Your workspace'} />
    <p>Membership roles apply to every active business in this workspace.</p>
    {session.capabilities.includes('members:manage') && !session.trusted_development ? <MemberAdministration /> : <p>Workspace administration requires Owner or Admin access.</p>}
    {!session.trusted_development && <InvitationAcceptance session={session} />}
  </>;
}
