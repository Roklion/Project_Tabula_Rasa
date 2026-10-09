import type { ReactNode } from 'react';
import { ApiError } from '../api/client';

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return <p role="status" aria-live="polite">{label}</p>;
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return <section className="empty"><h2>{title}</h2>{children && <p>{children}</p>}</section>;
}

export function SuccessNotice({ children }: { children: ReactNode }) {
  return <p role="status" className="notice success">{children}</p>;
}

const messages = {
  validation: 'Check the highlighted fields and try again.',
  conflict: 'This record changed or conflicts with another record. Your draft is preserved.',
  identity: 'Business access is unavailable. Sign in again or check your membership.',
  unexpected: 'The request could not be completed. Your draft is preserved. Check the latest record before trying a save again.',
};

export function ErrorNotice({ error, onReview }: { error: unknown; onReview?: () => void }) {
  const failure = error instanceof ApiError ? error : new ApiError('unexpected');
  const conflict = ['stale', 'conflict', 'duplicate', 'concurrent_write'].includes(failure.code);
  const validation = ['validation', 'reference', 'invariant', 'required', 'baseline_required', 'baseline_invalid'].includes(failure.code);
  const identity = ['unauthorized', 'forbidden'].includes(failure.code);
  return <div role="alert" className={'notice ' + (conflict ? 'warning' : 'error')}>
    <p>{messages[conflict ? 'conflict' : validation ? 'validation' : identity ? 'identity' : 'unexpected']}</p>
    {failure.fields.length > 0 && <ul>{failure.fields.map(field =>
      <li key={field.field}>{field.field}: Check this value.</li>)}</ul>}
    {failure.requestId && <p className="muted">Request reference: {failure.requestId}</p>}
    {onReview && <button type="button" onClick={event => { event.currentTarget.focus(); onReview(); }}>{conflict ? 'Review latest record' : 'Reload'}</button>}
  </div>;
}

export function Field({ id, label, error, children }: { id: string; label: string; error?: string; children: ReactNode }) {
  return <div className="field"><label htmlFor={id}>{label}</label>{children}
    {error && <p id={id + '-error'} role="alert" className="fieldError">{error}</p>}
  </div>;
}
