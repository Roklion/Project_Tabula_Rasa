import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, ApiError, type Schemas } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { EmptyState, ErrorNotice, Field, LoadingState, SuccessNotice } from '../../components/States';
import { UnsavedChanges } from '../../components/UnsavedChanges';
import { useProtectedMutation } from '../concurrency/mutations';

type PendingReceipt = { id: string; file: File; document?: Schemas['Document']; linked: boolean; error?: unknown };

export function ReceiptsPage() {
  const { recordId = '' } = useParams();
  return <ReceiptWorkflow key={recordId} recordId={recordId} />;
}

function ReceiptWorkflow({ recordId }: { recordId: string }) {
  const session = useEntity();
  const operation = useProtectedMutation(session, (action: () => Promise<void>) => action());
  const [pending, setPending] = useState<PendingReceipt[]>([]);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState('');
  const [failure, setFailure] = useState<unknown>();
  const [message, setMessage] = useState('');
  const [remove, setRemove] = useState<Schemas['Document']>();
  const linked = useQuery({ queryKey: [...resourceKey(session, 'documents'), 'transaction', recordId],
    queryFn: ({ signal }) => api.transactionDocuments(session, recordId, signal) });
  const inventory = useQuery({ queryKey: [...resourceKey(session, 'documents'), 'unreferenced'],
    queryFn: ({ signal }) => api.unreferencedDocuments(session, signal), enabled: linked.isSuccess });
  const transaction = useQuery({ queryKey: resourceKey(session, 'transactions'), queryFn: ({ signal }) => api.transactions(session, signal) });
  const row = transaction.data?.items.find(item => item.id === recordId);
  const writable = session.capabilities.includes('bookkeeping:write');
  const unresolved = pending.filter(item => !item.linked);
  async function transfer() {
    setBusy(true); setFailure(undefined); setMessage('');
    const next = [...pending];
    try {
      for (let index = 0; index < next.length; index++) {
        const item = { ...next[index] };
        if (item.linked) continue;
        item.error = undefined;
        try {
          if (!item.document) {
            setPhase('Uploading ' + item.file.name + '…');
            item.document = await api.uploadDocument(session, item.id, item.file);
          }
          setPhase('Linking ' + item.file.name + '…');
          await api.linkDocument(session, recordId, item.document.id);
          item.linked = true;
        } catch (error) { item.error = error; }
        next[index] = item; setPending([...next]);
      }
      const count = next.filter(item => item.linked).length;
      const remaining = next.length - count;
      if (remaining) setMessage(`${count} attached; ${remaining} unresolved. Uploaded files remain in Unreferenced receipts. Retry only the unresolved files.`);
      else { setMessage(`${count} ${count === 1 ? 'receipt' : 'receipts'} attached.`); setPending([]); }
    } finally { setBusy(false); setPhase(''); }
  }
  async function mutate(action: () => Promise<unknown>, success: string) {
    setBusy(true); setFailure(undefined); setMessage('');
    try { await action(); setMessage(success); setRemove(undefined); }
    catch (error) { setFailure(error); }
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
  async function download(doc: Schemas['Document']) {
    if (busy) return;
    setBusy(true); setPhase('Downloading receipt…'); setFailure(undefined);
    try {
      const content = await api.downloadDocument(session, doc.id);
      const url = URL.createObjectURL(content);
      const link = document.createElement('a'); link.href = url; link.download = doc.filename; link.click(); URL.revokeObjectURL(url);
    } catch (error) { setFailure(error); }
    finally { setBusy(false); setPhase(''); }
  }
  function documentView(doc: Schemas['Document']) {
    return <><span>{doc.filename} · {doc.byte_size === null ? 'Size unverified' : `${doc.byte_size} bytes`}</span>
      <details><summary>Inspect {doc.filename}</summary><dl><dt>File type</dt><dd>{doc.mime_type || 'Unverified'}</dd>
        <dt>Document ID</dt><dd>{doc.id}</dd><dt>SHA-256</dt><dd>{doc.sha256 || 'Unverified'}</dd></dl></details>
      {!doc.sha256 && <p className="muted">Integrity metadata is incomplete.</p>}
      <a aria-disabled={busy} href={`/api/v1/entities/${encodeURIComponent(session.entity.id)}/documents/${encodeURIComponent(doc.id)}/content`}
        onClick={event => { event.preventDefault(); void download(doc); }}>Download {doc.filename}</a></>;
  }
  if (linked.isPending) return <LoadingState label="Loading receipts…" />;
  if (linked.isError) return <><h1>Receipts</h1><Link to="/transactions">Back to transactions</Link><ErrorNotice error={linked.error} onReview={() => void linked.refetch()} />
    <p>Receipt storage must be configured for this business before receipts are available.</p></>;
  return <><h1>Receipts</h1><p className="lead">{row ? `${row.txn_date} · ${row.description || row.kind} · ${row.amount}` : 'Saved transaction'}</p>
    <Link to="/transactions">Back to transactions</Link><UnsavedChanges dirty={unresolved.length > 0 || busy} />
    {failure !== undefined && <ErrorNotice error={failure} />}
    {message && (unresolved.length ? <p role="alert" className="notice warning">{message}</p> : <SuccessNotice>{message}</SuccessNotice>)}
    {busy && <><LoadingState label={phase || 'Updating receipts…'} />
      {(phase.startsWith('Uploading') || phase.startsWith('Linking')) && <progress aria-label="Receipt upload progress" />}</>}
    <section className="surface editor"><h2>Linked receipts</h2>
      {!linked.data.items.length ? <EmptyState title="No receipts attached">Attach files or link an unreferenced receipt below.</EmptyState>
        : <ul className="recordList">{linked.data.items.map(doc => <li key={doc.id}><div>{documentView(doc)}</div>
          {writable && <button type="button" disabled={busy} onClick={() => setRemove(doc)}>Remove {doc.filename}</button>}</li>)}</ul>}
      {remove && <div role="alertdialog" aria-label="Remove receipt" className="notice warning"><p>Remove the reference to {remove.filename}? The stored file remains available in Unreferenced receipts.</p>
        <button type="button" disabled={busy} onClick={() => setRemove(undefined)}>Keep receipt</button>
        <button type="button" disabled={busy || operation.isPending} onClick={() => void operation.mutateAsync(() => mutate(() => api.unlinkDocument(session, recordId, remove.id), 'Receipt reference removed. File retained.'))}>Confirm remove</button></div>}
    </section>
    {writable && <section className="surface editor"><h2>Attach receipts</h2><p>PDF, PNG, JPG, JPEG, WEBP or HEIC; up to 20 MB per file, 200 MB per batch and 100 receipts per transaction.</p>
      <Field id="receipt-files" label="Receipt files"><input id="receipt-files" type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.heic" disabled={busy || unresolved.length > 0}
        onChange={event => { filesSelected(Array.from(event.target.files ?? [])); event.target.value = ''; }} /></Field>
      {pending.map(item => <div key={item.id}><p>{item.file.name}: {item.linked ? 'Attached' : item.document ? 'Uploaded; link pending' : 'Upload pending'}</p>
        {item.error !== undefined && <ErrorNotice error={item.error} />}</div>)}
      <div className="actions"><button type="button" disabled={busy || operation.isPending || !unresolved.length} onClick={() => void operation.mutateAsync(transfer)}>{pending.some(item => item.error !== undefined) ? 'Retry unresolved receipts' : 'Attach selected receipts'}</button>
        {!!unresolved.length && <button type="button" disabled={busy} onClick={() => { setPending([]); setMessage('Recovery cancelled. Uploaded files remain in Unreferenced receipts.'); }}>Cancel recovery</button>}</div>
    </section>}
    <section className="surface editor"><h2>Unreferenced receipts</h2>{inventory.isPending ? <LoadingState /> : inventory.isError ? <ErrorNotice error={inventory.error} onReview={() => void inventory.refetch()} /> : <>
      {!!inventory.data.needing_integrity && <p role="alert">{inventory.data.needing_integrity} files need integrity metadata before they can be linked.</p>}
      {!inventory.data.items.length ? <EmptyState title="No unreferenced receipts" /> : <ul className="recordList">{inventory.data.items.map(doc => <li key={doc.id}><div>{documentView(doc)}</div>
        {writable && <button type="button" disabled={busy || operation.isPending || unresolved.length > 0} onClick={() => void operation.mutateAsync(() => mutate(() => api.linkDocument(session, recordId, doc.id), 'Receipt linked.'))}>Link {doc.filename}</button>}</li>)}</ul>}
    </>}</section>
  </>;
}
