import { useQuery } from '@tanstack/react-query';
import { api, type Session } from '../../api/client';
import { accountQuery, resourceKey } from '../../api/query';

export function useReferenceChoices(session: Session) {
  const accounts = useQuery(accountQuery(session));
  const categories = useQuery({ queryKey: resourceKey(session, 'categories'), queryFn: ({ signal }) => api.categories(session, signal) });
  const payees = useQuery({ queryKey: resourceKey(session, 'payees'), queryFn: ({ signal }) => api.payees(session, signal) });
  const tags = useQuery({ queryKey: resourceKey(session, 'tags'), queryFn: ({ signal }) => api.tags(session, signal) });
  return { accounts: accounts.data?.items ?? [], categories: categories.data?.items ?? [],
    payees: payees.data?.items ?? [], tags: tags.data?.items ?? [],
    pending: [accounts, categories, payees, tags].some(query => query.isPending),
    error: [accounts, categories, payees, tags].find(query => query.isError)?.error,
  };
}

// Match historical-reference eligibility at the domain mutation boundary.
export function activeChoices<T extends { id: string; name: string; active: boolean }>(rows: T[], retainedIds: (string | undefined)[] = []) {
  return rows.filter(row => row.active || retainedIds.includes(row.id))
    .map(row => ({ ...row, name: row.active ? row.name : `${row.name} (inactive)` }));
}
