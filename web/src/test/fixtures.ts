import type { Session } from '../api/client';

export const session: Session = {
  actor_id: 'actor', organization_id: 'org', entity: { id: 'alpha', name: 'Alpha' },
  capabilities: ['bookkeeping:read', 'bookkeeping:write'], cache_scope: 'session-1',
  csrf_token: 'server-csrf', trusted_development: true,
};
