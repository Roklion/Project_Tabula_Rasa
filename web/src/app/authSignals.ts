/** Ask same-origin peers to discard stale scope and reload server authority. */
export function notifyPeerScopeChange() {
  if (typeof BroadcastChannel === 'undefined') return;
  const channel = new BroadcastChannel('tabula-auth');
  channel.postMessage('scope-changed');
  channel.close();
}
