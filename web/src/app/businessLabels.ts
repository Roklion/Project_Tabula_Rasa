import type { Schemas } from '../api/client';

/** Keep permitted same-name ledgers distinct without showing backing organizations. */
export function businessLabel(business: Schemas['EntityInfo'], choices: Schemas['EntityInfo'][]) {
  return choices.some(item => item.id !== business.id && item.name === business.name)
    ? `${business.name} (reference: ${business.id})` : business.name;
}
