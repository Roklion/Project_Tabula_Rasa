import { useState } from 'react';
import { api, type SessionState } from '../../api/client';
import { ErrorNotice, Field, SuccessNotice } from '../../components/States';
import { ActionButton } from '../../components/VisualPrimitives';

export function InvitationAcceptance({ session }: { session: SessionState }) {
  const [credential, setCredential] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [declined, setDeclined] = useState(false);
  async function respond(accept: boolean) {
    const submitted = credential;
    setCredential(''); setPending(true); setError(undefined); setDeclined(false);
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
    {error !== undefined && <ErrorNotice error={error} reauthenticationPath="/invitations" />}
  </section>;
}
