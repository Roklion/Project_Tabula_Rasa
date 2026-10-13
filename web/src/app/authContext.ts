import { createContext } from 'react';

export const AuthContext = createContext<{ logout: () => void }>({ logout: () => undefined });
