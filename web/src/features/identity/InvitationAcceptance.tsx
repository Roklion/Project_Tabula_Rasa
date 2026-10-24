import { useRef, useState } from 'react';
import { api, type Schemas, type SessionState } from '../../api/client';
import { ErrorNotice, Field, LoadingState, SuccessNotice } from '../../components/States';
import { ActionButton } from '../../components/VisualPrimitives';
import { notifyPeerScopeChange } from '../../app/authSignals';
import { roleLabel } from '../../app/roles';
import { uncertainIdentityCommand } from './commandOutcome';

export function InvitationAcceptance({ session }: { session: SessionState }) {
  const [credential, setCredential] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [declined, setDeclined] = useState(false);
  const [preview, setPreview] = useState<Schemas['InvitationPreview']>();
  const [accepted, setAccepted] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const submitting = useRef(false);
  async function review() {
    if (submitting.current) return;
    submitting.current = true; setPending(true); setError(undefined); setDeclined(false);
    try { setPreview(await api.previewInvitation(session, credential)); }
    catch (failure) { setCredential(''); setError(failure); }
    finally { submitting.current = false; setPending(false); }
  }
  async function respond(accept: boolean) {
    if (submitting.current || !preview || uncertain) return;
    submitting.current = true;
    const submitted = credential;
    setCredential(''); setPending(true); setError(undefined); setDeclined(false);
    let confirmed = false;
    try {
      await api.respondInvitation(session, submitted, accept);
      confirmed = true;
      if (accept) {
        setAccepted(true);
        await api.selectEntity(session, preview.business_id);
        notifyPeerScopeChange();
        window.location.replace('/');
      }
      else setDeclined(true);
    } catch (failure) { setError(failure); setUncertain(!confirmed && uncertainIdentityCommand(failure)); }
    finally { setPreview(undefined); submitting.current = false; setPending(false); }
  }
  return <section className="surface"><h2>Respond to an invitation</h2>
    <p>Sign in with the invited account, then paste the credential shared privately by the business administrator. A recent sign-in is required.</p>
    <form onSubmit={event => { event.preventDefault(); if (preview) void respond(true); else void review(); }}>
      <Field id="invitation-credential" label="Invitation credential"><input id="invitation-credential" type="password" autoComplete="off" spellCheck={false}
        value={credential} onChange={event => { setCredential(event.target.value); setPreview(undefined); setAccepted(false); }} required disabled={pending || uncertain} /></Field>
      {preview && <section aria-label="Invited business"><h3>{preview.business_name}</h3>
        <p>Business reference: {preview.business_id}</p><p>Your role in this business: {roleLabel(preview.role)}</p>
        <p>Accepting grants access only to this business. Existing active membership keeps its role.</p></section>}
      <div className="actions">{preview
        ? <><ActionButton type="submit" disabled={pending}>Accept invitation</ActionButton>
          <ActionButton type="button" disabled={pending} onClick={() => void respond(false)}>Decline invitation</ActionButton></>
        : <ActionButton type="submit" disabled={!credential || pending || uncertain}>Review invitation</ActionButton>}</div>
    </form>
    {accepted && <SuccessNotice>Invitation accepted. If the business does not open, reload My Businesses to select it. Do not submit this invitation again.</SuccessNotice>}
    {uncertain && <p role="alert">The invitation outcome could not be confirmed. Reload My Businesses to inspect your access before responding again. Do not resubmit this credential.</p>}
    {pending && <LoadingState label="Checking invitation… Please wait for confirmation." />}
    {declined && <SuccessNotice>Invitation declined.</SuccessNotice>}
    {error !== undefined && <ErrorNotice error={error} reauthenticationPath="/invitations" />}
  </section>;
}
