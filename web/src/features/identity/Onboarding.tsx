import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type Schemas, type SessionState } from '../../api/client';
import { ErrorNotice, Field, LoadingState } from '../../components/States';
import { ActionButton, PageHeader } from '../../components/VisualPrimitives';
import { InvitationAcceptance } from './InvitationAcceptance';

/** Persist only an opaque receipt key. Authority always comes from the session/API. */
function receiptKey(session: SessionState, organization?: string) {
  return `tabula-setup:${session.actor_id}:${organization ?? 'first'}`;
}

export function LedgerSetup({ session, organization }: { session: SessionState; organization?: string }) {
  const key = receiptKey(session, organization);
  const [step, setStep] = useState(1);
  const [workspace, setWorkspace] = useState('');
  const [business, setBusiness] = useState('');
  const [pending, setPending] = useState(false);
  const [checking, setChecking] = useState(true);
  const [interrupted, setInterrupted] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [error, setError] = useState<unknown>();
  const submitted = useRef<Schemas['BootstrapRequest'] | undefined>(undefined);
  const confirmed = useRef<Schemas['BootstrapResult'] | undefined>(undefined);
  const mounted = useRef(false);
  const request = useRef<string | undefined>(undefined);

  async function finish(result: Schemas['BootstrapResult']) {
    if (result.state !== 'ready' || !result.entity_id) return;
    // Select through the authorized server boundary, including additional businesses.
    const current = await api.session();
    if (!mounted.current) return;
    if (current.actor_id !== session.actor_id || current.state === 'needs_setup') throw new Error('Business context unavailable');
    if (current.entity.id !== result.entity_id) await api.selectEntity(current, result.entity_id);
    if (!mounted.current) return;
    sessionStorage.removeItem(key);
    window.location.replace('/');
  }

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    async function resume() {
      try {
        request.current = sessionStorage.getItem(key) ?? undefined;
        if (request.current) {
          const result = await api.bootstrapStatus(request.current, controller.signal);
          if (controller.signal.aborted) return;
          if (result.state === 'ready') await finish(result);
          else setInterrupted(true);
        }
      } catch (failure) { if (!controller.signal.aborted) setError(failure); }
      finally { if (!controller.signal.aborted) setChecking(false); }
    }
    void resume();
    return () => { mounted.current = false; controller.abort(); };
    // The parent keys this component by authenticated actor and organization.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function create() {
    if (pending) return;
    setPending(true); setError(undefined);
    try {
      if (confirmed.current) { await finish(confirmed.current); return; }
      if (!request.current) {
        const id = crypto.randomUUID();
        // A failed storage write must stop before a remote create can happen.
        sessionStorage.setItem(key, id);
        request.current = id;
      }
      submitted.current ??= { request_id: request.current, workspace_name: organization ? 'Existing workspace' : workspace.trim(), business_name: business.trim() };
      setAttempted(true);
      let result: Schemas['BootstrapResult'];
      try {
        result = organization && session.state !== 'needs_setup'
          ? await api.bootstrapBusiness(session, submitted.current)
          : await api.bootstrapWorkspace(session, submitted.current);
      } catch (failure) {
        if (failure instanceof ApiError && !['unavailable', 'unexpected'].includes(failure.code)) throw failure;
        // One bounded readback after an uncertain response; no automatic create retry.
        const status = await api.bootstrapStatus(request.current);
        if (status.state !== 'ready') throw failure;
        result = status;
      }
      confirmed.current = result;
      if (mounted.current) await finish(result);
    } catch (failure) { if (mounted.current) setError(failure); }
    finally { if (mounted.current) setPending(false); }
  }

  if (checking) return <LoadingState label="Checking interrupted setup…" />;
  return <section aria-label="Start a fresh ledger">
    <h2>{organization ? 'Add a business' : 'Start a fresh ledger'}</h2>
    <p role="status">Step {step} of 2 · {step === 1 ? 'Name your business' : 'Review bookkeeping defaults'}</p>
    {interrupted && <p>Setup was interrupted. Re-enter the same names to resume. Your original request will be reused.</p>}
    <form onSubmit={event => { event.preventDefault(); if (step === 1) setStep(2); else void create(); }}>
      {step === 1 ? <>
        {!organization && <Field id="setup-workspace" label="Workspace name"><input id="setup-workspace" required maxLength={160} value={workspace}
          onChange={event => setWorkspace(event.target.value)} /></Field>}
        <Field id="setup-business" label="Business name"><input id="setup-business" required maxLength={160} value={business}
          onChange={event => setBusiness(event.target.value)} /></Field>
      </> : <>
        <p>{!organization && <>Workspace: {workspace.trim()} · </>}Business: {business.trim()}</p>
        <Field id="setup-defaults" label="Bookkeeping defaults"><select id="setup-defaults" defaultValue="standard"><option value="standard">Standard basic bookkeeping</option></select></Field>
        <p>Start with the supported chart of accounts and Income/Expense categories. Opening balances start at zero. Review accounts before recording your first transaction.</p>
        <p>External connections are optional and coming later. You can invite collaborators later from Workspace &amp; members.</p>
        {!attempted && <ActionButton disabled={pending} onClick={() => setStep(1)}>Back</ActionButton>}
      </>}
      <div className="actions"><ActionButton tone="primary" type="submit" pending={pending}
        disabled={step === 1 && (!business.trim() || !organization && !workspace.trim())}>
        {step === 1 ? 'Review defaults' : attempted ? 'Retry same setup' : 'Create ledger'}</ActionButton></div>
    </form>
    {pending && <LoadingState label="Creating your ledger and selecting the business…" />}
    {error !== undefined && <><ErrorNotice error={error} /><p>Setup could not be confirmed. Retry uses the same request. If this page was refreshed, use the original names. Enable session storage if your browser blocks it.</p></>}
  </section>;
}

export function Onboarding({ session }: { session: SessionState }) {
  const [path, setPath] = useState<'choose' | 'fresh' | 'invite' | 'migration'>(() => window.location.pathname === '/invitations' ? 'invite' : 'choose');
  return <><PageHeader title="Workspace setup required" description="Welcome. Choose how to reach your first ledger." />
    {path === 'choose' && <div className="actions">
      <ActionButton tone="primary" onClick={() => setPath('fresh')}>Start fresh</ActionButton>
      <ActionButton onClick={() => setPath('invite')}>Join an invited workspace</ActionButton>
      <ActionButton onClick={() => setPath('migration')}>Move existing Sheets books</ActionButton>
    </div>}
    {path === 'fresh' && <LedgerSetup key={session.actor_id} session={session} />}
    {path === 'invite' && <InvitationAcceptance session={session} />}
    {path === 'migration' && <section><h2>Existing live books</h2><p>Do not create a replacement ledger here. Ask your operator to follow the explicit migration and cutover process. Browser setup does not import, claim or switch authority for existing Sheets books.</p></section>}
    {path !== 'choose' && <div className="actions"><a className="button" href="/">Choose another setup path</a></div>}
  </>;
}
