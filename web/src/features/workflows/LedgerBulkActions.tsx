import { useState } from 'react';
import { api, type Schemas } from '../../api/client';
import { useEntity } from '../../app/context';
import { ConfirmationDialog } from '../../components/ConfirmationDialog';
import { ActionButton, SectionHeader } from '../../components/VisualPrimitives';
import { ErrorNotice, Field, SuccessNotice } from '../../components/States';
import { useProtectedMutation } from '../concurrency/mutations';
import { activeChoices, useReferenceChoices } from '../concurrency/useReferenceChoices';

const mixed = 'Mixed / Multiple values';
function without(changes: Schemas['TransactionBulkChanges'], field: keyof Schemas['TransactionBulkChanges']) {
  const next = { ...changes }; delete next[field]; return next;
}
function shared(rows: Schemas['Transaction'][], field: 'category_id' | 'payee_id') {
  return rows.length && rows.every(row => row[field] === rows[0][field]) ? rows[0][field] : undefined;
}
function amountTotal(rows: Schemas['Transaction'][]) {
  const cents = rows.reduce((sum, row) => sum + BigInt(row.amount.replace('.', '').replace('-', '')), 0n);
  return `${cents / 100n}.${(cents % 100n).toString().padStart(2, '0')}`;
}

export function LedgerBulkActions({ selected, loaded, onCopy, onApplied, onAction }: {
  selected: Schemas['LedgerItem'][]; loaded: Schemas['Transaction'][];
  onCopy: (draft: Schemas['TransactionChanges'], sourceId: string) => void;
  onApplied: (message: string) => void; onAction?: () => void;
}) {
  const session = useEntity();
  const choices = useReferenceChoices(session);
  const records = selected.map(row => loaded.find(record => record.id === row.record_id));
  const transactions = records.filter((row): row is Schemas['Transaction'] => Boolean(row));
  const protectedSelection = selected.some(row => row.entry_type !== 'transaction' || Boolean(row.source_type)) || records.some(row => !row);
  const selection = { transaction_ids: selected.map(row => row.record_id), expected: transactions.map(row => ({ id: row.id, baseline: row.baseline })) };
  const categoryKind = transactions.length && transactions.every(row => row.kind === transactions[0].kind) && transactions[0].kind !== 'Transfer' ? transactions[0].kind : undefined;
  const [changes, setChanges] = useState<Schemas['TransactionBulkChanges']>({});
  const [failure, setFailure] = useState<unknown>();
  const [result, setResult] = useState<string>();
  const [confirmation, setConfirmation] = useState<'update' | 'delete'>();
  const [acknowledged, setAcknowledged] = useState(false);
  const mutation = useProtectedMutation(session, async (action: 'copy' | 'update' | 'delete') => {
    if (action === 'copy') { onCopy(await api.prepareTransactionCopy(session, transactions[0].id, transactions[0].baseline), transactions[0].id); return; }
    const response = action === 'update' ? await api.bulkUpdateTransactions(session, { ...selection, changes })
      : await api.bulkDeleteTransactions(session, selection);
    const message = `${response.count ?? selected.length} transaction(s) ${action === 'update' ? 'updated' : 'permanently deleted'}.`;
    setResult(message);
    setChanges({}); setConfirmation(undefined); setAcknowledged(false); onApplied(message);
  });
  async function apply(action: 'copy' | 'update' | 'delete') {
    onAction?.();
    setFailure(undefined); setResult(undefined);
    try { await mutation.mutateAsync(action); } catch (error) { setFailure(error); setConfirmation(undefined); }
  }
  const tagValue = transactions.length && transactions.every(row => JSON.stringify([...row.tag_ids].sort()) === JSON.stringify([...transactions[0].tag_ids].sort())) ? transactions[0].tag_ids : undefined;
  const retainedPayees = transactions.length && shared(transactions, 'payee_id') !== undefined ? [shared(transactions, 'payee_id')] : [];
  const retainedTags = choices.tags.filter(tag => transactions.length && transactions.every(row => row.tag_ids.includes(tag.id))).map(tag => tag.id);
  return <section className="surface editor" aria-label="Selected transaction actions"><SectionHeader title="Selected transaction actions" />
    <p role="status">{selected.length} selected logical record(s)</p>
    {protectedSelection && <p>Journal selections support export only. Mixed-use and depreciation entries are managed through their source workflows. Select only ordinary transactions to copy, change or delete.</p>}
    {result && <SuccessNotice>{result}</SuccessNotice>}{failure !== undefined && <><ErrorNotice error={failure} /><p>Leave Bulk mode and select records again to review fresh values before another attempt.</p></>}
    <fieldset disabled={mutation.isPending || protectedSelection || selected.length === 0 || choices.pending || Boolean(choices.error)}>
      <ActionButton disabled={selected.length !== 1} onClick={() => void apply('copy')}>Copy transaction</ActionButton>
      <h3>Apply changes</h3><p>Only checked fields change. Tags replace the complete set.</p>
      {categoryKind ? <Field id="bulk-category" label="Category"><label><input type="checkbox" checked={'category_id' in changes} onChange={event => setChanges(event.target.checked ? { ...changes, category_id: shared(transactions, 'category_id') ?? '' } : without(changes, 'category_id'))} /> Apply Category to all selected</label>
        <select id="bulk-category" value={changes.category_id ?? shared(transactions, 'category_id') ?? ''} onChange={event => setChanges({ ...changes, category_id: event.target.value })}><option value="">{shared(transactions, 'category_id') === undefined ? mixed : 'Choose category'}</option>{choices.categories.filter(row => row.kind === categoryKind).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></Field>
        : <p>Category changes require only Income or only Expense transactions.</p>}
      <Field id="bulk-payee" label="Payee / customer"><label><input type="checkbox" checked={'payee_id' in changes} onChange={event => setChanges(event.target.checked ? { ...changes, payee_id: shared(transactions, 'payee_id') ?? '' } : without(changes, 'payee_id'))} /> Apply Payee to all selected</label>
        {shared(transactions, 'payee_id') === undefined && !('payee_id' in changes) && <p>{mixed}</p>}
        <select id="bulk-payee" value={changes.payee_id ?? shared(transactions, 'payee_id') ?? ''} onChange={event => setChanges({ ...changes, payee_id: event.target.value })}><option value="">None</option>{activeChoices(choices.payees, retainedPayees).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></Field>
      <Field id="bulk-tags" label="Tags"><label><input type="checkbox" checked={'tag_ids' in changes} onChange={event => setChanges(event.target.checked ? { ...changes, tag_ids: tagValue ?? [] } : without(changes, 'tag_ids'))} /> Apply Tags to all selected</label>
        {tagValue === undefined && !('tag_ids' in changes) && <p>{mixed}</p>}
        <select id="bulk-tags" multiple value={changes.tag_ids ?? tagValue ?? []} onChange={event => setChanges({ ...changes, tag_ids: Array.from(event.target.selectedOptions, option => option.value) })}>{activeChoices(choices.tags, retainedTags).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></Field>
      <div className="actions"><ActionButton tone="primary" disabled={!Object.keys(changes).length || ('category_id' in changes && !changes.category_id)} onClick={() => setConfirmation('update')}>Review selected changes</ActionButton>
        <ActionButton tone="destructive" onClick={() => setConfirmation('delete')}>Permanently delete selected</ActionButton></div>
    </fieldset>
    {confirmation && <ConfirmationDialog title={confirmation === 'delete' ? 'Permanently delete selected transactions' : 'Apply changes to selected transactions'} keepLabel="Keep reviewing" confirmLabel={confirmation === 'delete' ? 'Confirm permanent deletion' : 'Confirm selected changes'}
      confirmTone={confirmation === 'delete' ? 'destructive' : 'primary'} confirmDisabled={confirmation === 'delete' && !acknowledged} pending={mutation.isPending} onKeep={() => { setConfirmation(undefined); setAcknowledged(false); }}
      onConfirm={() => { if (confirmation !== 'delete' || acknowledged) void apply(confirmation); }}>
      {confirmation === 'delete' ? <>{selected.length} transactions with aggregate absolute amount {amountTotal(transactions)} will be permanently deleted. Linked receipt files remain available as unreferenced documents.
        <label><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} /> I understand that this cannot be undone.</label></>
        : <>{selected.length} transactions will receive these changes: {Object.keys(changes).map(field => ({ category_id: 'Category', payee_id: 'Payee', tag_ids: 'Tags' })[field as keyof Schemas['TransactionBulkChanges']]).join(', ')}. Other fields remain as loaded.</>}
    </ConfirmationDialog>}
  </section>;
}
