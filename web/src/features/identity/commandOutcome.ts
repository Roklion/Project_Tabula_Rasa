import { ApiError } from '../../api/client';

/** A failed transport may have committed; only explicit safe rejections allow resubmission. */
export function uncertainIdentityCommand(failure: unknown) {
  return !(failure instanceof ApiError && [
    'validation', 'invariant', 'required', 'forbidden', 'unauthorized',
    'reauthentication_required', 'stale', 'conflict', 'concurrent_write',
    'invitation_invalid', 'invitation_used', 'invitation_expired',
  ].includes(failure.code));
}
