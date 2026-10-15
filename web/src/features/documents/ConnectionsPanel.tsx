import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type Schemas } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { ActionButton, SectionHeader } from '../../components/VisualPrimitives';
import { ErrorNotice, LoadingState, SuccessNotice } from '../../components/States';
import { ConfirmationDialog } from '../../components/ConfirmationDialog';

const labels = { not_configured: 'Not configured', pending: 'Ready for owner connection',
  connected: 'Connected', disconnected: 'Disconnected', reconnect_required: 'Reconnect required' };

export function ConnectionsPanel() {
  const session = useEntity();
  const cache = useQueryClient();
  const [confirm, setConfirm] = useState<(Schemas['ConnectionChange'] & { label: string }) | null>(null);
  const query = useQuery({ queryKey: resourceKey(session, 'connections'),
    queryFn: ({ signal }) => api.connectionStatus(session, signal), retry: false });
  const mutation = useMutation({ mutationFn: (command: Schemas['ConnectionChange']) =>
    api.changeConnection(session, command), retry: false,
    onSettled: () => Promise.all(['connections', 'documents'].map(resource =>
      cache.invalidateQueries({ queryKey: resourceKey(session, resource) }))) });
  const connected = query.data?.status === 'connected';
  const label = connected ? 'Disconnect Google Drive' :
    query.data?.status === 'pending' ? 'Connect Google Drive' : 'Reconnect Google Drive';
  return <section aria-label="External connections">
    <SectionHeader title="Google Drive connection" />
    <p>Receipt storage for {session.entity.name}. Your Google connection is separate from signing in.</p>
    {query.isPending && <LoadingState />}
    {query.error && <ErrorNotice error={query.error} operation="read" onReview={() => void query.refetch()} />}
    {query.data && <p role="status">{labels[query.data.status]}</p>}
    <p>An operator provisions the approved Google grant and receipt folder. Connect and disconnect require
      signing in within the last five minutes. If access has expired, sign out and sign in again.</p>
    {mutation.error && <ErrorNotice error={mutation.error} onReview={() => void query.refetch()} />}
    {mutation.isSuccess && <SuccessNotice>{mutation.data.status === 'connected' ?
      'Google Drive is connected for this business.' : 'Google Drive is disconnected for this business.'}</SuccessNotice>}
    {query.data && query.data.status !== 'not_configured' &&
      <ActionButton disabled={query.isFetching || mutation.isPending} onClick={() =>
        setConfirm({ revision: query.data!.revision, connect: !connected, label })}>{label}</ActionButton>}
    {confirm && <ConfirmationDialog title={confirm.label} keepLabel="Cancel" confirmLabel={confirm.label}
      pending={mutation.isPending} onKeep={() => setConfirm(null)}
      onConfirm={() => mutation.mutate({ revision: confirm.revision, connect: confirm.connect },
        { onSettled: () => setConfirm(null) })}>
      {!confirm.connect ? 'Stop this business from accessing its Google receipts. Files and ledger links are preserved. ' +
        'This disconnect does not revoke Google consent; ask the operator to revoke it separately.' :
        'Enable receipt access using the grant and folder provisioned for this business.'}
    </ConfirmationDialog>}
  </section>;
}
