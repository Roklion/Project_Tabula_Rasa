import { useEffect, useId, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ActionButton, type ActionTone } from './VisualPrimitives';

export function ConfirmationDialog({ title, children, keepLabel, confirmLabel, onKeep, onConfirm, pending = false, confirmTone = 'primary' }: {
  title: string; children: ReactNode; keepLabel: string; confirmLabel: string;
  onKeep: () => void; onConfirm: () => void; pending?: boolean; confirmTone?: ActionTone;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const description = useId();
  useEffect(() => {
    const dialog = ref.current!;
    const opener = document.activeElement;
    dialog.showModal();
    return () => {
      dialog.close();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
      else document.getElementById('main')?.focus();
    };
  }, []);
  return createPortal(<dialog ref={ref} role="alertdialog" aria-modal="true" aria-label={title}
    aria-describedby={description} className="confirmation notice warning"
    onCancel={event => { event.preventDefault(); if (!pending) onKeep(); }}
    onKeyDown={event => {
      if (event.key !== 'Tab') return;
      const buttons = Array.from(ref.current!.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));
      const first = buttons[0], last = buttons.at(-1);
      if (!first || !last) { event.preventDefault(); return; }
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }}>
    <p id={description}>{children}</p>
    <div className="actions"><ActionButton disabled={pending} onClick={onKeep}>{keepLabel}</ActionButton>
      <ActionButton tone={confirmTone} pending={pending} onClick={onConfirm}>{confirmLabel}</ActionButton></div>
  </dialog>, document.body);
}
