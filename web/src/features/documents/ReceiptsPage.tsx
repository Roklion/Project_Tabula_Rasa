import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, ApiError, type Schemas } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { EmptyState, ErrorNotice, Field, LoadingState, SuccessNotice } from '../../components/States';
import { UnsavedChanges } from '../../components/UnsavedChanges';
import { useProtectedMutation } from '../concurrency/mutations';
import { downloadBlob } from '../../components/downloadBlob';
import { ConfirmationDialog } from '../../components/ConfirmationDialog';
import { useLoadedRecord } from '../concurrency/useLoadedRecord';
import { ActionButton, PageHeader, SectionHeader } from '../../components/VisualPrimitives';

type PendingReceipt = { id: string; file: File; document?: Schemas['Document']; linked: boolean; error?: unknown };

function recoverySummary(items: PendingReceipt[]) {
  const unresolved = items.filter(item => !item.linked);
  const uploaded = unresolved.filter(item => item.document).length;
  const unconfirmed = unresolved.length - uploaded;
  return [
    uploaded ? `${uploaded} confirmed uploaded ${uploaded === 1 ? 'file remains' : 'files remain'} in Unreferenced receipts.` : '',
    unconfirmed ? `${unconfirmed} ${unconfirmed === 1 ? 'file has' : 'files have'} no confirmed upload.` : '',
  ].filter(Boolean).join(' ');
}

export function ReceiptsPage() {
  const { recordId = '' } = useParams();
  return <ReceiptWorkflow key={recordId} recordId={recordId} />;
}

export function MixedUseReceiptsPage() {
  const { recordId = '' } = useParams();
  return <MixedUseReceiptOwner key={recordId} recordId={recordId} />;
}

function MixedUseReceiptOwner({ recordId }: { recordId: string }) {
  const session = useEntity();
  const query = useLoadedRecord(session, 'mixed-use', recordId, api.mixedUseSource);
  if (query.initializing) return <><h1>Mixed-use receipts</h1><LoadingState /></>;
  if (!query.initialized || !query.data) return <><h1>Mixed-use receipts</h1><Link to="/mixed-use">Back to mixed-use expenses</Link>
    <ErrorNotice error={query.error} onReview={() => void query.refetch()} /></>;
  return <ReceiptWorkflow recordId={recordId} initialSource={query.data} />;
}

function ReceiptWorkflow({ recordId, initialSource }: { recordId: string; initialSource?: Schemas['MixedUse'] }) {
  const session = useEntity();
  const [source, setSource] = useState(initialSource);
  const sourceMetadata = useRef(initialSource);
  const [reviewRequired, setReviewRequired] = useState(false);
  const [review, setReview] = useState(false);
  const [reloading, setReloading] = useState(false);
  const mixed = initialSource !== undefined;
  const back = mixed ? '/mixed-use/' + encodeURIComponent(recordId) : '/transactions';
  const backLabel = mixed ? 'Back to mixed-use expense' : 'Back to transactions';
  const transport = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    transport.current = controller;
    return () => { controller.abort(); transport.current = null; };
  }, []);
  const operation = useProtectedMutation(session, (action: () => Promise<void>) => action());
  const [pending, setPending] = useState<PendingReceipt[]>([]);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState('');
  const [failure, setFailure] = useState<unknown>();
  const [message, setMessage] = useState('');
  const [remove, setRemove] = useState<Schemas['Document']>();
  const linked = useQuery({ queryKey: [...resourceKey(session, 'documents'), mixed ? 'mixed-use' : 'transaction', recordId],
    queryFn: ({ signal }) => mixed ? api.mixedUseDocuments(session, recordId, signal) : api.transactionDocuments(session, recordId, signal) });
  const inventory = useQuery({ queryKey: [...resourceKey(session, 'documents'), 'unreferenced'],
    queryFn: ({ signal }) => api.unreferencedDocuments(session, signal), enabled: linked.isSuccess });
  const transaction = useQuery({ queryKey: resourceKey(session, 'transactions'), queryFn: ({ signal }) => api.transactions(session, signal), enabled: !mixed });
  const row = transaction.data?.items.find(item => item.id === recordId);
  const writable = session.capabilities.includes('bookkeeping:write');
  const blocked = busy || reloading || review || reviewRequired;
  const unresolved = pending.filter(item => !item.linked);
  function rememberFailure(error: unknown) {
    if (mixed && error instanceof ApiError && ['stale', 'baseline_invalid', 'baseline_required', 'not_found'].includes(error.code)) setReviewRequired(true);
  }
  function sourceChanged(next: Schemas['MixedUse']) {
    sourceMetadata.current = next;
    setSource(next);
  }
  async function link(documentId: string) {
    if (mixed) {
      const expected = sourceMetadata.current;
      if (!expected?.baseline) throw new ApiError('baseline_required');
      sourceChanged(await api.linkMixedUseDocument(session, recordId, { baseline: expected.baseline, document_id: documentId }));
    } else await api.linkDocument(session, recordId, documentId);
  }
  async function unlink(documentId: string) {
    if (mixed) {
      const expected = sourceMetadata.current;
      if (!expected?.baseline) throw new ApiError('baseline_required');
      sourceChanged(await api.unlinkMixedUseDocument(session, recordId, documentId, expected.baseline));
    } else await api.unlinkDocument(session, recordId, documentId);
  }
  async function reloadSource() {
    setReloading(true);
    try {
      sourceChanged(await api.mixedUseSource(session, recordId));
      await Promise.all([
        linked.refetch({ throwOnError: true }),
        inventory.refetch({ throwOnError: true }),
      ]);
      setReviewRequired(false); setFailure(undefined); setReview(false);
    } catch (error) { setFailure(error); setReview(false); }
    finally { setReloading(false); }
  }
  async function transfer() {
    const controller = transport.current;
    if (!controller || controller.signal.aborted) return;
    setBusy(true); setFailure(undefined); setMessage('');
    const next = [...pending];
    try {
      for (let index = 0; index < next.length; index++) {
        if (controller.signal.aborted) return;
        const item = { ...next[index] };
        if (item.linked) continue;
        item.error = undefined;
        try {
          if (!item.document) {
            setPhase('Uploading ' + item.file.name + '…');
            item.document = await api.uploadDocument(session, item.id, item.file);
          }
          // A confirmed upload survives scope loss as an unreferenced receipt.
          // Do not continue linking/uploading after this private view unmounts.
          if (controller.signal.aborted) return;
          setPhase('Linking ' + item.file.name + '…');
          await link(item.document.id);
          item.linked = true;
        } catch (error) { item.error = error; rememberFailure(error); }
        next[index] = item; setPending([...next]);
        // A changed source must be reviewed before more files are uploaded.
        if (mixed && item.error instanceof ApiError && ['stale', 'baseline_invalid', 'baseline_required', 'not_found'].includes(item.error.code)) break;
      }
      const count = next.filter(item => item.linked).length;
      const remaining = next.length - count;
      if (remaining) setMessage(`${count} attached; ${remaining} unresolved. ${recoverySummary(next)} Retry only the unresolved files.`);
      else { setMessage(`${count} ${count === 1 ? 'receipt' : 'receipts'} attached.`); setPending([]); }
    } finally { setBusy(false); setPhase(''); }
  }
  async function mutate(action: () => Promise<unknown>, success: string) {
    setBusy(true); setFailure(undefined); setMessage('');
    try { await action(); setMessage(success); setRemove(undefined); }
    catch (error) { setRemove(undefined); setFailure(error); rememberFailure(error); }
    finally { setBusy(false); }
  }
  function filesSelected(files: File[]) {
    setFailure(undefined); setMessage('');
    if (files.some(file => !/\.(pdf|png|jpe?g|webp|heic)$/i.test(file.name) || !file.size || file.size > 20 * 1024 * 1024)
      || files.reduce((sum, file) => sum + file.size, 0) > 200 * 1024 * 1024 || files.length + (linked.data?.items.length ?? 0) > 100) {
      setFailure(new ApiError('validation')); return;
    }
    setPending(files.map(file => ({ id: crypto.randomUUID().replaceAll('-', ''), file, linked: false })));
  }
  function cancelRecovery() {
    setMessage(['Recovery cancelled.', recoverySummary(pending),
      unresolved.some(item => !item.document) ? 'Check Unreferenced receipts before selecting those files again.' : '',
    ].filter(Boolean).join(' '));
    setPending([]);
  }
  async function download(doc: Schemas['Document']) {
    if (busy) return;
    const controller = transport.current;
    if (!controller || controller.signal.aborted) return;
    setBusy(true); setPhase('Downloading receipt…'); setFailure(undefined);
    try {
      const content = await api.downloadDocument(session, doc.id, controller.signal);
      if (!controller.signal.aborted) downloadBlob(content, doc.filename);
    } catch (error) { setFailure(error); }
    finally { setBusy(false); setPhase(''); }
  }
  function documentView(doc: Schemas['Document']) {
    return <><span>{doc.filename} · {doc.byte_size === null ? 'Size unverified' : `${doc.byte_size} bytes`}</span>
      <details className="receiptMetadata"><summary>Inspect {doc.filename}</summary><dl><dt>File type</dt><dd>{doc.mime_type || 'Unverified'}</dd>
        <dt>Document ID</dt><dd>{doc.id}</dd><dt>SHA-256</dt><dd>{doc.sha256 || 'Unverified'}</dd></dl></details>
      {!doc.sha256 && <p className="muted">Integrity metadata is incomplete.</p>}
      <a className="button action-secondary" aria-label={'Download ' + doc.filename} aria-disabled={busy} href={`/api/v1/entities/${encodeURIComponent(session.entity.id)}/documents/${encodeURIComponent(doc.id)}/content`}
        onClick={event => { event.preventDefault(); void download(doc); }}>Download</a></>;
  }
  if (linked.isPending) return <LoadingState label="Loading receipts…" />;
  if (linked.isError) return <><PageHeader title={mixed ? 'Mixed-use receipts' : 'Receipts'} actions={<Link className="button action-secondary" to={back}>{backLabel}</Link>} />
    <section className="surface"><SectionHeader title="Receipts unavailable" description="Receipt storage must be configured for this business before receipts are available." />
      <ErrorNotice error={linked.error} operation="read" onReview={() => void linked.refetch()} /></section></>;
  return <><PageHeader title={mixed ? 'Mixed-use receipts' : 'Receipts'} description={source ? `${source.txn_date} · ${source.description || 'Mixed-use expense'} · Total ${source.total_expense} · Allocated ${source.allocated_amount}` : row ? `${row.txn_date} · ${row.description || row.kind} · ${row.amount}` : 'Saved transaction'}
    actions={<Link className="button action-secondary" to={back}>{backLabel}</Link>} />
    {source && <p>Receipts belong to source {source.id}. The linked ledger projection uses the same references.
      {source.recurring_schedule_id && ' This occurrence owns its receipts; the recurring template has none.'}</p>}
    <UnsavedChanges dirty={unresolved.length > 0 || busy} />
    {!writable && <p className="notice neutral">Read-only access: inspect and download receipts for this {mixed ? 'source' : 'transaction'}.</p>}
    {mixed && writable && <><button type="button" disabled={busy || reloading} onClick={() => setReview(true)}>Review latest source</button>
      {reviewRequired && <p role="alert">The source changed or is unavailable. Review the latest saved source before changing receipt references. Pending files are retained.</p>}
      {review && <ConfirmationDialog title="Review source" keepLabel="Keep loaded source" confirmLabel="Reload source"
        pending={reloading} onKeep={() => setReview(false)} onConfirm={() => void reloadSource()}>
        Reload the latest saved source and review it before changing receipts. Pending files and confirmed uploads are retained.
      </ConfirmationDialog>}</>}
    {failure !== undefined && <ErrorNotice error={failure} />}
    {message && (unresolved.length || message.startsWith('Recovery cancelled.') ? <p role="alert" className="notice warning">{message}</p> : <SuccessNotice>{message}</SuccessNotice>)}
    {busy && <><LoadingState label={phase || 'Updating receipts…'} />
      {(phase.startsWith('Uploading') || phase.startsWith('Linking')) && <progress aria-label="Receipt upload progress" />}</>}
    <section className="surface editor"><SectionHeader title="Linked receipts" description="Removing a receipt reference retains its stored file in Unreferenced receipts." />
      {!linked.data.items.length ? <EmptyState title="No receipts attached">Attach files or link an unreferenced receipt below.</EmptyState>
        : <ul className="recordList">{linked.data.items.map(doc => <li key={doc.id}><div>{documentView(doc)}</div>
          {writable && <ActionButton aria-label={'Remove ' + doc.filename} disabled={blocked} onClick={event => { event.currentTarget.focus(); setRemove(doc); }}>Remove receipt</ActionButton>}</li>)}</ul>}
      {remove && <ConfirmationDialog title="Remove receipt" keepLabel="Keep receipt" confirmLabel="Confirm remove"
        pending={busy || operation.isPending} onKeep={() => setRemove(undefined)}
        onConfirm={() => void operation.mutateAsync(() => mutate(() => unlink(remove.id), 'Receipt reference removed. File retained.'))}>
        Remove the reference to {remove.filename}? The stored file remains available in Unreferenced receipts.
      </ConfirmationDialog>}
    </section>
    {writable && <section className="surface editor"><SectionHeader title="Attach receipts" description={`PDF, PNG, JPG, JPEG, WEBP or HEIC; up to 20 MB per file, 200 MB per batch and 100 receipts per ${mixed ? 'source' : 'transaction'}.`} />
      <Field id="receipt-files" label="Receipt files"><input id="receipt-files" type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.heic" disabled={blocked || unresolved.length > 0}
        onChange={event => { filesSelected(Array.from(event.target.files ?? [])); event.target.value = ''; }} /></Field>
      {!!pending.length && <ul className="receiptQueue" aria-label="Selected receipts">{pending.map(item => <li key={item.id}><p>{item.file.name}: {item.linked ? 'Attached' : item.document ? 'Uploaded; link pending' : 'Upload pending'}</p>
        {item.error !== undefined && <ErrorNotice error={item.error} />}</li>)}</ul>}
      <div className="actions formActions"><ActionButton tone="primary" pending={busy || operation.isPending} disabled={blocked || !unresolved.length} onClick={() => void operation.mutateAsync(transfer)}>{pending.some(item => item.error !== undefined) ? 'Retry unresolved receipts' : 'Attach selected receipts'}</ActionButton>
        {!!unresolved.length && <ActionButton disabled={busy} onClick={cancelRecovery}>Cancel recovery</ActionButton>}</div>
    </section>}
    <section className="surface editor"><SectionHeader title="Unreferenced receipts" description="Confirmed uploads remain available here when linking fails or a reference is removed. Inspect this list before selecting an unconfirmed file again." />
      {inventory.isPending ? <LoadingState /> : inventory.isError ? <ErrorNotice error={inventory.error} operation="read" onReview={() => void inventory.refetch()} /> : <>
      {!!inventory.data.needing_integrity && <p role="alert" className="notice warning">{inventory.data.needing_integrity} files need integrity metadata before they can be linked.</p>}
      {!inventory.data.items.length ? <EmptyState title="No unreferenced receipts" /> : <ul className="recordList">{inventory.data.items.map(doc => <li key={doc.id}><div>{documentView(doc)}</div>
        {writable && <ActionButton aria-label={'Link ' + doc.filename} disabled={blocked || operation.isPending || unresolved.length > 0} onClick={() => void operation.mutateAsync(() => mutate(() => link(doc.id), 'Receipt linked.'))}>Link receipt</ActionButton>}</li>)}</ul>}
    </>}</section>
  </>;
}
