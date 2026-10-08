import { useEffect, useState, type ReactNode } from 'react';
import { api, type Schemas, type Session } from '../api/client';
import { ErrorNotice, LoadingState } from '../components/States';
import { ScopeBoundary } from './ScopeBoundary';
import { EntitySelectionContext } from './entitySelectionContext';

export function ContextBoundary({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ session?: Session; error?: unknown }>({});
  const [generation, setGeneration] = useState(0);
  const [entities, setEntities] = useState<Schemas['EntityInfo'][]>([]);
  const [entityError, setEntityError] = useState<unknown>();
  const [switching, setSwitching] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api.session(controller.signal).then(
      session => { if (!controller.signal.aborted) setState({ session }); },
      error => { if (!controller.signal.aborted) setState({ error }); },
    );
    api.entities(controller.signal).then(
      result => { if (!controller.signal.aborted) { setEntities(result.items); setEntityError(undefined); } },
      error => { if (!controller.signal.aborted) { setEntities([]); setEntityError(error); } },
    );
    return () => controller.abort();
  }, [generation]);
  if (state.error) return <main className="standalone"><h1>Project Tabula Rasa</h1>
    <ErrorNotice error={state.error} onReview={() => { setState({}); setGeneration(value => value + 1); }} />
  </main>;
  if (!state.session) return <main className="standalone"><LoadingState label="Loading business context…" /></main>;
  async function select(id: string) {
    if (!state.session) return;
    setSwitching(true);
    try { setState({ session: await api.selectEntity(state.session, id) }); }
    catch (error) { setState({ error }); }
    finally { setSwitching(false); }
  }
  return <EntitySelectionContext.Provider value={{ items: entities, select }}>
    {switching && <LoadingState label="Switching business…" />}
    {entityError !== undefined && state.session.trusted_development && <div className="standalone">
      <p>Business choices could not be loaded.</p><ErrorNotice error={entityError} onReview={() => window.location.reload()} />
    </div>}
    <div inert={switching}><ScopeBoundary session={state.session}>{children}</ScopeBoundary></div>
  </EntitySelectionContext.Provider>;
}
