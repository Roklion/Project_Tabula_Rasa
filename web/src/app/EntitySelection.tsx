import { useContext, useState } from 'react';
import { ConfirmationDialog } from '../components/ConfirmationDialog';
import { EntitySelectionContext } from './entitySelectionContext';
import { businessLabel } from './businessLabels';
import { useIsMutating } from '@tanstack/react-query';

export function EntitySelector({ activeId }: { activeId: string }) {
  const selection = useContext(EntitySelectionContext);
  const [next, setNext] = useState<string>();
  const pending = useIsMutating() > 0 || Boolean(selection?.pending);
  if (!selection || selection.items.length < 2) return null;
  return <><label htmlFor="business-selector">Select business</label>
    <select id="business-selector" disabled={pending} value={activeId} onChange={event => { event.currentTarget.focus(); setNext(event.target.value); }}>
      {selection.items.map(item => <option key={item.id} value={item.id}>{businessLabel(item, selection.items)}</option>)}
    </select>
    {next && next !== activeId && <ConfirmationDialog title="Switch business" keepLabel="Keep current business"
      confirmLabel="Discard draft and switch" pending={pending} onKeep={() => setNext(undefined)}
      onConfirm={() => void selection.select(next).then(() => setNext(undefined))}>
      Switch to {selection.items.find(item => item.id === next)?.name ?? 'the selected business'}?
      <p>Business reference: {next}</p>
      Discard any unsaved draft? Records and forms will reload for the selected business.
    </ConfirmationDialog>}
  </>;
}
