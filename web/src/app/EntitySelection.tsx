import { useContext, useState } from 'react';
import { EntitySelectionContext } from './entitySelectionContext';
import { useIsMutating } from '@tanstack/react-query';

export function EntitySelector({ activeId }: { activeId: string }) {
  const selection = useContext(EntitySelectionContext);
  const [next, setNext] = useState<string>();
  const pending = useIsMutating() > 0;
  if (!selection || selection.items.length < 2) return null;
  return <><label htmlFor="business-selector">Select business</label>
    <select id="business-selector" disabled={pending} value={activeId} onChange={event => setNext(event.target.value)}>
      {selection.items.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select>
    {next && next !== activeId && <div role="alertdialog" aria-label="Switch business" className="notice warning">
      <p>Switch business and discard any unsaved draft? Records and forms will reload for the selected business.</p>
      <button type="button" onClick={() => setNext(undefined)}>Keep current business</button>
      <button type="button" disabled={pending} onClick={() => void selection.select(next)}>Discard draft and switch</button>
    </div>}
  </>;
}
