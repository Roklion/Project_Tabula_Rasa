import type { Session } from '../api/client';

export const session: Session = {
  state: 'ready',
  actor_id: 'actor', organization_id: 'org', entity: { id: 'alpha', name: 'Alpha' },
  capabilities: ['bookkeeping:read', 'bookkeeping:write', 'bookkeeping:import'], cache_scope: 'session-1',
  csrf_token: 'server-csrf', trusted_development: true,
};
