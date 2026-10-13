import type { ButtonHTMLAttributes, ReactNode } from 'react';

export type ActionTone = 'primary' | 'secondary' | 'destructive';

/** Presentation only: callers retain submission, confirmation and mutation ownership. */
export function ActionButton({ tone = 'secondary', pending = false, disabled, className = '', children, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { tone?: ActionTone; pending?: boolean }) {
  return <button type="button" {...props} className={`action-${tone} ${className}`.trim()}
    disabled={disabled || pending} aria-busy={pending || undefined}>{children}</button>;
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return <header className="pageHeader"><div><h1>{title}</h1>{description && <p className="lead">{description}</p>}</div>
    {actions && <div className="actions">{actions}</div>}</header>;
}

export function SectionHeader({ title, description }: { title: string; description?: ReactNode }) {
  return <header className="sectionHeader"><h2>{title}</h2>{description && <p>{description}</p>}</header>;
}

/** Keep wide tables inside a named, keyboard-scrollable region. */
export function TableRegion({ label, children }: { label: string; children: ReactNode }) {
  return <div className="tableScroll" role="region" aria-label={label} tabIndex={0}>{children}</div>;
}

/** A labeled field group; form state and validation stay with the existing field owners. */
export function FormSection({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return <section className="formSection"><header className="formSectionHeader"><h3>{title}</h3>
    {description && <p>{description}</p>}</header><div className="formGrid">{children}</div></section>;
}
