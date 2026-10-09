import { useCallback } from 'react';
import { ConfirmationDialog } from './ConfirmationDialog';
import { useBeforeUnload, useBlocker } from 'react-router-dom';

export function UnsavedChanges({ dirty }: { dirty: boolean }) {
  const blocker = useBlocker(dirty);
  useBeforeUnload(useCallback((event: BeforeUnloadEvent) => {
    if (dirty) event.preventDefault();
  }, [dirty]));
  if (blocker.state !== 'blocked') return null;
  return <ConfirmationDialog title="Unsaved changes" keepLabel="Keep editing" confirmLabel="Discard draft and leave"
    onKeep={() => blocker.reset()} onConfirm={() => blocker.proceed()}>
    You have unsaved changes. Leave this page and discard the draft?
  </ConfirmationDialog>;
}
