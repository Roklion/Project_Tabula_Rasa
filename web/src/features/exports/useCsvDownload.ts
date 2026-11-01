import { useEffect, useRef, useState } from 'react';
import { useEntity } from '../../app/context';
import { downloadBlob } from '../../components/downloadBlob';

/** Stop a pending private download when navigation or business selection unmounts it. */
export function useCsvDownload() {
  const session = useEntity();
  const pending = useRef(new Set<AbortController>());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  useEffect(() => {
    const controllers = pending.current;
    return () => { for (const controller of controllers) controller.abort(); controllers.clear(); };
  }, []);
  async function download(read: (signal: AbortSignal) => Promise<Blob>, filename: string) {
    if (busy) return;
    const controller = new AbortController(); pending.current.add(controller);
    setBusy(true); setError(undefined);
    try {
      const content = await read(controller.signal);
      if (!controller.signal.aborted) downloadBlob(content, filename.replace(/(\.[^.]+)$/, `-${session.entity.currency_code}$1`));
    } catch (failure) { if (!controller.signal.aborted) setError(failure); }
    finally {
      pending.current.delete(controller);
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return { busy, error, download };
}
