import { useState } from 'react';
import { useEntity } from '../../app/context';
import { PageHeader } from '../../components/VisualPrimitives';
import { UnsavedChanges } from '../../components/UnsavedChanges';
import { TransactionImportsPage } from './TransactionImportsPage';
import { MileageImport } from './MileageImport';

export function DataBackupPage() {
  const session = useEntity();
  const [transactionDirty, setTransactionDirty] = useState(false);
  const [mileageDirty, setMileageDirty] = useState(false);
  return <><PageHeader title="Data & backup" description={<>Imports for {session.entity.name}.</>} />
    <UnsavedChanges dirty={transactionDirty || mileageDirty} />
    {session.capabilities.includes('bookkeeping:write') ? <>
      <TransactionImportsPage onDirtyChange={setTransactionDirty} />
      <MileageImport onDirtyChange={setMileageDirty} />
    </> : <p>Importing requires write access to this business.</p>}
  </>;
}
