import { useEffect, useState, type ReactNode } from 'react';
import { api, type Session } from '../api/client';
import { ErrorNotice, LoadingState } from '../components/States';
import { ScopeBoundary } from './ScopeBoundary';

export function ContextBoundary({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ session?: Session; error?: unknown }>({});
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    api.session(controller.signal).then(
      session => { if (!controller.signal.aborted) setState({ session }); },
      error => { if (!controller.signal.aborted) setState({ error }); },
    );
    return () => controller.abort();
  }, [generation]);
  if (state.error) return <main className="standalone"><h1>Project Tabula Rasa</h1>
    <ErrorNotice error={state.error} onReview={() => { setState({}); setGeneration(value => value + 1); }} />
  </main>;
  if (!state.session) return <main className="standalone"><LoadingState label="Loading business context…" /></main>;
  return <ScopeBoundary session={state.session}>{children}</ScopeBoundary>;
}
