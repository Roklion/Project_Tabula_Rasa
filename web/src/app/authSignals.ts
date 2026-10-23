/** Ask same-origin peers to discard stale scope and reload server authority. */
export function notifyPeerScopeChange() {
  if (typeof BroadcastChannel === 'undefined') return;
  const channel = new BroadcastChannel('tabula-auth');
  channel.postMessage('scope-changed');
  channel.close();
}

/** Membership edits may affect another tab's scope without changing ours. */
export function notifyPeerAuthorityCheck() {
  if (typeof BroadcastChannel === 'undefined') return;
  const channel = new BroadcastChannel('tabula-auth');
  channel.postMessage('authority-check');
  channel.close();
}
