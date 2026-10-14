import { useState } from 'react';
import { useEntity } from '../../app/context';
import { PageHeader } from '../../components/VisualPrimitives';
import { UnsavedChanges } from '../../components/UnsavedChanges';
import { TransactionImportsPage } from './TransactionImportsPage';
import { MileageImport } from './MileageImport';
import { FinancialCsvExports } from '../exports/FinancialCsvExports';

export function DataBackupPage() {
  const session = useEntity();
  const [transactionDirty, setTransactionDirty] = useState(false);
  const [mileageDirty, setMileageDirty] = useState(false);
  return <><PageHeader title="Data & backup" description={<>Imports and downloads for {session.entity.name}.</>} />
    <FinancialCsvExports embedded />
    <UnsavedChanges dirty={transactionDirty || mileageDirty} />
    {['bookkeeping:read', 'bookkeeping:write', 'bookkeeping:import'].every(capability => session.capabilities.includes(capability)) ? <>
      <TransactionImportsPage onDirtyChange={setTransactionDirty} />
      <MileageImport onDirtyChange={setMileageDirty} />
    </> : <p>Importing requires import access to this business (Owner, Admin or Accountant).</p>}
  </>;
}
