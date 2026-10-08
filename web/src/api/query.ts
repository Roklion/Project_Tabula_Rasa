import { QueryClient, queryOptions, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, type AccountCreate, type Session } from './client';

export const resourceKey = (session: Session, resource: string) =>
  ['private', session.cache_scope, session.entity.id, resource] as const;

export function createPrivateCache() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (count, error) => count < 1 && error instanceof ApiError && error.code === 'unavailable',
      },
      mutations: { retry: false },
    },
  });
}

export const accountQuery = (session: Session) => queryOptions({
  queryKey: resourceKey(session, 'accounts'),
  queryFn: ({ signal }) => api.accounts(session, signal),
});

export function useCreateAccount(session: Session) {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (body: AccountCreate) => api.createAccount(session, body),
    retry: false,
    onSettled: () => cache.invalidateQueries({ queryKey: resourceKey(session, 'accounts') }),
  });
}
