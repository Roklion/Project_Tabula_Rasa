import { useCallback } from 'react';
import { useBeforeUnload, useBlocker } from 'react-router-dom';

export function UnsavedChanges({ dirty }: { dirty: boolean }) {
  const blocker = useBlocker(dirty);
  useBeforeUnload(useCallback((event: BeforeUnloadEvent) => {
    if (dirty) event.preventDefault();
  }, [dirty]));
  if (blocker.state !== 'blocked') return null;
  return <div role="alertdialog" aria-label="Unsaved changes" aria-describedby="unsaved-message" className="notice warning">
    <p id="unsaved-message">You have unsaved changes. Leave this page and discard the draft?</p>
    <button type="button" autoFocus onClick={() => blocker.reset()}>Keep editing</button>
    <button type="button" onClick={() => blocker.proceed()}>Discard draft and leave</button>
  </div>;
}
