import { FilePicker } from '../../components/FilePicker';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, type Schemas } from '../../api/client';
import { resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { ConfirmationDialog } from '../../components/ConfirmationDialog';
import { ErrorNotice, SuccessNotice } from '../../components/States';
import { ActionButton, TableRegion } from '../../components/VisualPrimitives';

export function MileageImport({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) {
  const session = useEntity();
  const cache = useQueryClient();
  const [file, setFile] = useState<File>();
  const [prepared, setPrepared] = useState<Schemas['MileageImportPreview']>();
  const [confirm, setConfirm] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [imported, setImported] = useState<number>();
  const preview = useMutation({ mutationFn: (source: File) => api.previewQuickBooksMileage(session, source), retry: false,
    onSuccess: result => { setPrepared(result); setUncertain(false); setImported(undefined); commit.reset(); } });
  const commit = useMutation({ mutationFn: (source: File) => api.importQuickBooksMileage(session, source), retry: false,
    onSuccess: result => { setImported(result.imported); setPrepared(undefined); setUncertain(false); },
    onError: error => setUncertain(!(error instanceof ApiError) || ['unavailable', 'unexpected'].includes(error.code)),
    onSettled: () => { setConfirm(false); void cache.invalidateQueries({ queryKey: resourceKey(session, 'mileage') }); } });
  const pending = preview.isPending || commit.isPending;
  useEffect(() => onDirtyChange(Boolean(file) && imported === undefined), [file, imported, onDirtyChange]);
  const columns = prepared?.source_rows[0] ? Object.keys(prepared.source_rows[0]) : [];
  return <section className="surface" aria-labelledby="mileage-import-heading">
    <h2 id="mileage-import-heading">Import QuickBooks mileage</h2>
    <p>Upload a QuickBooks Online Download Trips CSV. Only unique Business trips are imported;
      Personal and Unreviewed trips are skipped. Mileage stays separate from financial transactions.</p>
    <p>Use UTF-8 CSV files up to 25 MB and 1,000 source rows per batch.</p>
    <FilePicker id="quickbooks-mileage-file" label="QuickBooks mileage CSV" accept=".csv" disabled={pending} onFiles={files => {
      setFile(files[0]); setPrepared(undefined); setImported(undefined); setUncertain(false);
      preview.reset(); commit.reset();
    }} />
    <div className="actions"><ActionButton disabled={!file || pending} pending={preview.isPending} onClick={() => {
      setPrepared(undefined); if (file) preview.mutate(file);
    }}>{uncertain ? 'Review mileage import status' : 'Preview mileage import'}</ActionButton>
      <Link to="/mileage" className="button">View mileage log</Link>
    </div>
    {preview.isError && <ErrorNotice error={preview.error} operation="read" />}
    {commit.isError && <ErrorNotice error={commit.error} />}
    {uncertain && <p role="alert" className="notice warning">The import status is not confirmed.
      Inspect the mileage log, then review this file again before another import. Do not assume no trips were saved.</p>}
    {imported !== undefined && <SuccessNotice>Imported {imported} mileage trips.</SuccessNotice>}
    {prepared && <>
      <p role="status">Mileage ready: {prepared.summary.ready}. Duplicates: {prepared.summary.duplicates}.
        Personal skipped: {prepared.summary.personal_skipped}. Unreviewed skipped: {prepared.summary.unreviewed_skipped}.
        Validation errors: {prepared.errors.length}.</p>
      {prepared.errors.length > 0 && <div role="alert" className="notice error"><p>Fix these mileage import errors before continuing:</p>
        <ul>{prepared.errors.map((message, index) => <li key={index}>{message}</li>)}</ul></div>}
      {([
        ['Duplicate rows', prepared.duplicate_rows], ['Personal rows', prepared.personal_rows],
        ['Unreviewed rows', prepared.unreviewed_rows],
      ] as const).map(([label, rows]) => rows.length > 0 && <p key={label}>{label} skipped: {rows.join(', ')}.</p>)}
      {columns.length > 0 && <TableRegion label="QuickBooks mileage source preview"><table>
        <caption>First 50 source rows</caption><thead><tr>{columns.map(column => <th scope="col" key={column}>{column}</th>)}</tr></thead>
        <tbody>{prepared.source_rows.map((row, index) => <tr key={index}>{columns.map(column => <td className="tableText" key={column}>{row[column]}</td>)}</tr>)}</tbody>
      </table></TableRegion>}
      <ActionButton tone="primary" disabled={pending || uncertain || prepared.errors.length > 0 || prepared.summary.ready === 0}
        onClick={event => { event.currentTarget.focus(); setConfirm(true); }}>Import validated mileage</ActionButton>
    </>}
    {confirm && prepared && <ConfirmationDialog title="Import validated mileage" keepLabel="Keep reviewing"
      confirmLabel="Confirm mileage import" pending={commit.isPending} onKeep={() => setConfirm(false)}
      onConfirm={() => { if (file) commit.mutate(file); }}>
      Import {prepared.summary.ready} ready Business trips into {session.entity.name}? References and duplicates are checked again before saving.
    </ConfirmationDialog>}
  </section>;
}
