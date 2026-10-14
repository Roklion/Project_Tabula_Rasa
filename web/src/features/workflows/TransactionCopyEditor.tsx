import { useState } from 'react';
import { api, type Schemas } from '../../api/client';
import { useEntity } from '../../app/context';
import { SuccessNotice } from '../../components/States';
import { ActionButton } from '../../components/VisualPrimitives';
import { TransactionFields } from '../concurrency/BookkeepingEditors';
import { useReferenceChoices } from '../concurrency/useReferenceChoices';
import { CreateEditor } from './CreateEditor';

export function TransactionCopyEditor({ draft, sourceId, onClose }: {
  draft: Schemas['TransactionChanges']; sourceId: string; onClose: () => void;
}) {
  const session = useEntity();
  const choices = useReferenceChoices(session);
  const [created, setCreated] = useState(false);
  if (created) return <><SuccessNotice>Transaction copied.</SuccessNotice>
    <ActionButton onClick={onClose}>Back to records</ActionButton></>;
  return <><p>Create an independent transaction copied from {sourceId}. Receipts are not copied.</p>
    <CreateEditor<Schemas['TransactionChanges']> title="Save transaction copy" initial={() => draft} onClose={onClose} prefilledDraft
      canSubmit={values => !choices.pending && !choices.error && choices.accounts.some(row => row.id === values.account_id && row.active) &&
        (values.kind === 'Transfer' ? choices.accounts.some(row => row.id === values.to_account_id && row.active && row.id !== values.account_id)
          : choices.categories.some(row => row.id === values.category_id && row.kind === values.kind))}
      create={async (values, transaction_id) => {
        const result = await api.createTransaction(session, { ...values, transaction_id, copied_from_transaction_id: sourceId,
          to_account_id: values.kind === 'Transfer' ? values.to_account_id : '', category_id: values.kind === 'Transfer' ? '' : values.category_id });
        setCreated(true);
        return result;
      }}
      fields={form => <TransactionFields form={form} creating />} />
  </>;
}
