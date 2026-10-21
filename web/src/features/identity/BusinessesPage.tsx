import { useContext, useState } from 'react';
import { EntitySelectionContext } from '../../app/entitySelectionContext';
import { useEntity } from '../../app/context';
import { ActionButton, PageHeader } from '../../components/VisualPrimitives';
import { LedgerSetup } from './Onboarding';

/** Independent business creation is available regardless of the current business role. */
export function BusinessesPage() {
  const session = useEntity();
  const selection = useContext(EntitySelectionContext);
  const [creating, setCreating] = useState(false);
  return <div className="workflowSections"><PageHeader title="My Businesses" description="Each business has its own membership and ledger. Creating another business does not copy anyone else’s access." />
    <section aria-label="Available businesses"><h2>Your businesses</h2><ul className="recordList">
      {selection?.items.map(item => <li key={item.id}><span>{item.name} <span className="muted">{item.role?.replace('_', ' ')}</span></span>
        {item.id === session.entity.id && <span>Selected business</span>}</li>)}
    </ul><p>Use Select business in the navigation to switch businesses.</p></section>
    {!session.trusted_development && (creating ? <LedgerSetup key={session.actor_id} session={session} />
      : <div className="actions"><ActionButton tone="primary" onClick={() => setCreating(true)}>Create another business</ActionButton></div>)}
    <section aria-label="Other ways to get started"><h2>Other ways to get started</h2>
      <div className="actions"><a className="button" href="/invitations">Join an invited business</a></div>
      <p>Moving existing Sheets books requires the approved operator migration and cutover process. Creating a business does not import or claim those books.</p>
    </section>
  </div>;
}
