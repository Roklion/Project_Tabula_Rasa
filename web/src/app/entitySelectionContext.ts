import { createContext } from 'react';
import type { Schemas } from '../api/client';

export const EntitySelectionContext = createContext<{
  pending: boolean; items: Schemas['EntityInfo'][]; select: (id: string) => Promise<void>;
} | undefined>(undefined);
