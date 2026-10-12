import { useEffect, useRef, useState, type ReactNode } from 'react';
import { api, ApiError, type Schemas, type SessionState } from '../api/client';
import { ErrorNotice, LoadingState } from '../components/States';
import { ScopeBoundary } from './ScopeBoundary';
import { EntitySelectionContext } from './entitySelectionContext';
import { AuthContext } from './authContext';

const authorityKey = (session: SessionState) => JSON.stringify([session.actor_id, session.cache_scope,
  session.organization_id, session.entity?.id, session.capabilities]);

export function ContextBoundary({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ session?: SessionState; error?: unknown; signedOut?: boolean }>(
    () => window.location.pathname === '/signed-out' ? { signedOut: true } : {});
  const identityGeneration = useRef(0);
  // Retain no private identity/entity data after a failed authority check.
  const logoutContext = useRef<{ csrf_token: string } | undefined>(undefined);
  const [generation, setGeneration] = useState(0);
  const [entities, setEntities] = useState<Schemas['EntityInfo'][]>([]);
  const [entityError, setEntityError] = useState<unknown>();
  const [switching, setSwitching] = useState(false);
  const [selectionError, setSelectionError] = useState<unknown>();
  useEffect(() => {
    if (!state.session || state.session.trusted_development) return;
    const controller = new AbortController();
    const expected = identityGeneration.current;
    let checking = false;
    const check = async () => {
      if (checking || document.visibilityState === 'hidden') return;
      checking = true;
      try {
        const session = await api.session(controller.signal);
        if (!controller.signal.aborted && expected === identityGeneration.current) {
          if (authorityKey(session) !== authorityKey(state.session!)) {
            identityGeneration.current++;
            setEntities([]); setEntityError(undefined); setSelectionError(undefined);
          }
          logoutContext.current = { csrf_token: session.csrf_token };
          setState({ session });
        }
      } catch (error) {
        if (!controller.signal.aborted && expected === identityGeneration.current) {
          identityGeneration.current++; setEntities([]); setEntityError(undefined); setSelectionError(undefined);
          setState({ error });
        }
      } finally { checking = false; }
    };
    let lastActivity = 0;
    const activity = () => {
      if (document.visibilityState === 'hidden' || Date.now() - lastActivity < 60_000) return;
      lastActivity = Date.now();
      void api.activity(state.session!).catch(() => void check());
    };
    const channel = typeof BroadcastChannel === 'undefined' ? undefined : new BroadcastChannel('tabula-auth');
    if (channel) channel.onmessage = event => {
      if (event.data !== 'signed-out') return;
      logoutContext.current = undefined;
      identityGeneration.current++; setEntities([]); setEntityError(undefined); setSelectionError(undefined);
      setState({ signedOut: true });
    };
    const timer = window.setInterval(() => void check(), 60_000);
    window.addEventListener('focus', check);
    window.addEventListener('pageshow', check);
    window.addEventListener('tabula:identity-check', check);
    document.addEventListener('visibilitychange', check);
    window.addEventListener('pointerdown', activity);
    window.addEventListener('keydown', activity);
    return () => {
      controller.abort(); channel?.close(); window.clearInterval(timer);
      window.removeEventListener('focus', check); window.removeEventListener('pageshow', check);
      window.removeEventListener('tabula:identity-check', check);
      document.removeEventListener('visibilitychange', check);
      window.removeEventListener('pointerdown', activity); window.removeEventListener('keydown', activity);
    };
  }, [state.session]);
  async function logout() {
    const context = logoutContext.current;
    logoutContext.current = undefined;
    // Unmount immediately; server failure never keeps private drafts on screen.
    identityGeneration.current++;
    setEntities([]); setEntityError(undefined); setSelectionError(undefined);
    setState({ signedOut: true });
    const channel = typeof BroadcastChannel === 'undefined' ? undefined : new BroadcastChannel('tabula-auth');
    channel?.postMessage('signed-out'); channel?.close();
    try { await api.logout(context); }
    catch (error) { setState({ error, signedOut: true }); }
  }
  useEffect(() => {
    if (window.location.pathname === '/signed-out') return;
    const controller = new AbortController();
    const expected = identityGeneration.current;
    api.session(controller.signal).then(
      session => {
        if (!controller.signal.aborted && expected === identityGeneration.current) {
          logoutContext.current = { csrf_token: session.csrf_token };
          setState({ session });
          if (session.state === 'needs_setup') { setEntities([]); return; }
          api.entities(controller.signal).then(
            result => { if (!controller.signal.aborted && expected === identityGeneration.current) { setEntities(result.items); setEntityError(undefined); } },
            error => { if (!controller.signal.aborted && expected === identityGeneration.current) { setEntities([]); setEntityError(error); } },
          );
        }
      },
      error => { if (!controller.signal.aborted && expected === identityGeneration.current) setState({ error }); },
    );
    return () => controller.abort();
  }, [generation]);
  if (state.signedOut || state.error instanceof ApiError && state.error.code === 'unauthorized')
    return <main className="standalone"><h1>Project Tabula Rasa</h1><p>You are signed out. Sign in to continue.</p>
      {state.error !== undefined && <ErrorNotice error={state.error} />}
      {window.location.pathname === '/signed-out' && <p>Sign-in did not complete. You can try again.</p>}
      <a href="/api/v1/auth/login">Sign in</a></main>;
  if (state.error) return <main className="standalone"><h1>Project Tabula Rasa</h1>
    <ErrorNotice error={state.error} onReview={() => { setState({}); setGeneration(value => value + 1); }} />
    <button onClick={() => void logout()}>Sign out</button>
  </main>;
  if (!state.session) return <main className="standalone"><LoadingState label="Loading business context…" /></main>;
  if (state.session.state === 'needs_setup') return <main className="standalone"><h1>Workspace setup required</h1>
    <p>You are signed in, but no active business is selected. Ask your organization owner to arrange access.</p>
    <button onClick={() => void logout()}>Sign out</button></main>;
  async function select(id: string) {
    if (!state.session || state.session.state === 'needs_setup') return;
    setSwitching(true);
    const expected = identityGeneration.current;
    setSelectionError(undefined);
    try {
      const session = await api.selectEntity(state.session, id);
      if (expected === identityGeneration.current) {
        logoutContext.current = { csrf_token: session.csrf_token };
        setState({ session });
      }
    }
    catch (error) { setSelectionError(error); }
    finally { setSwitching(false); }
  }
  return <AuthContext.Provider value={{ logout: () => void logout() }}><EntitySelectionContext.Provider value={{ items: entities, select, pending: switching }}>
    {switching && <LoadingState label="Switching business…" />}
    {selectionError !== undefined && <div className="standalone">
      <p>Business switching could not be confirmed. Your current business and draft are preserved.</p>
      <ErrorNotice error={selectionError} />
    </div>}
    {entityError !== undefined && state.session.trusted_development && <div className="standalone">
      <p>Business choices could not be loaded.</p><ErrorNotice error={entityError} onReview={() => window.location.reload()} />
    </div>}
    <div inert={switching}><ScopeBoundary session={state.session}>{children}</ScopeBoundary></div>
  </EntitySelectionContext.Provider></AuthContext.Provider>;
}
