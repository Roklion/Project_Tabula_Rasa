import { createContext, useContext } from 'react';
import type { Session } from '../api/client';

export const EntityContext = createContext<Session | null>(null);

export function useEntity() {
  const session = useContext(EntityContext);
  if (!session) throw new Error('Server context required.');
  return session;
}
