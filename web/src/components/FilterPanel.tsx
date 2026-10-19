import { useId, useState, type ReactNode } from 'react';
import { useEntity } from '../app/context';

/** Persist presentation only. Filter values and results remain owned by the page. */
export function FilterPanel({ name, title, label, summary, children }: {
  name: string; title: string; label: string; summary: string; children: ReactNode;
}) {
  const session = useEntity();
  const id = useId();
  const key = JSON.stringify(['tabula-filter-panel', session.cache_scope, session.actor_id, session.organization_id, session.entity.id, name]);
  const [collapsed, setCollapsed] = useState(() => {
    try { return sessionStorage.getItem(key) === 'collapsed'; } catch { return false; }
  });
  return <section className="surface filterPanel" aria-label={label}>
    <h2><button type="button" className="filterToggle" aria-expanded={!collapsed} aria-controls={id} aria-describedby={id + '-summary'}
      onClick={() => {
        setCollapsed(!collapsed);
        try { sessionStorage.setItem(key, collapsed ? 'expanded' : 'collapsed'); } catch { /* Storage is optional. */ }
      }}><span>{title}</span><span>{collapsed ? 'Show filters' : 'Hide filters'}</span></button></h2>
    <p id={id + '-summary'} className="fieldHint">{summary}</p>
    <div id={id} hidden={collapsed} className="filterContent">{children}</div>
  </section>;
}
