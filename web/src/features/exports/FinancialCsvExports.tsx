import { api } from '../../api/client';
import { useEntity } from '../../app/context';
import { ActionButton, PageHeader, SectionHeader } from '../../components/VisualPrimitives';
import { ErrorNotice, LoadingState } from '../../components/States';
import { useCsvDownload } from './useCsvDownload';

export function FinancialCsvExports() {
  const session = useEntity();
  const transfer = useCsvDownload();
  const today = new Date().toISOString().slice(0, 10);
  return <><PageHeader title="Data & backup" description={`Downloads for ${session.entity.name}.`} /><section className="surface" aria-label="Financial CSV exports">
    <SectionHeader title="Exports" description={`Financial CSV downloads for ${session.entity.name}.`} />
    <p>Transactions and journal postings are separate CSVs. Each download reads the current business's ledger, including inactive accounts. An empty ledger produces column headings.</p>
    <div className="actions">
      <ActionButton disabled={transfer.busy} onClick={() => void transfer.download(signal => api.downloadTransactionsCsv(session, signal), `tabula-rasa-${today}.csv`)}>Download transactions CSV</ActionButton>
      <ActionButton disabled={transfer.busy} onClick={() => void transfer.download(signal => api.downloadJournalPostingsCsv(session, signal), `tabula-rasa-journals-${today}.csv`)}>Download journal postings CSV</ActionButton>
    </div>
    {transfer.busy && <LoadingState label="Preparing CSV download…" />}
    {transfer.error !== undefined && <ErrorNotice operation="read" error={transfer.error} />}
  </section></>;
}
