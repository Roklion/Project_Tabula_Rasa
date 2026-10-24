import type { Schemas } from '../api/client';
import { roleLabel } from './roles';

/** Keep permitted same-name ledgers distinct without showing backing organizations. */
export function businessLabel(business: Schemas['EntityInfo'], choices: Schemas['EntityInfo'][]) {
  return choices.some(item => item.id !== business.id && item.name === business.name)
    ? `${business.name} (reference: ${business.id})` : business.name;
}

export function businessChoiceLabel(business: Schemas['EntityInfo'], choices: Schemas['EntityInfo'][]) {
  const role = roleLabel(business.role);
  return businessLabel(business, choices) + (role ? ' · ' + role : '');
}
