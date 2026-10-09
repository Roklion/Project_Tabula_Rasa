import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useEntity } from './context';
import styles from './Shell.module.css';

import { navigation } from './navigation';

export function Shell() {
  const session = useEntity();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  return <div className={styles.shell}>
    <a className={styles.skip} href="#main">Skip to content</a>
    <aside className={styles.sidebar}>
      <div className={styles.brand}>Project <br />Tabula Rasa</div>
      <div className={styles.context}><span className="muted">Business</span>
        <strong>{session.entity.name}</strong>
        {session.trusted_development && <span className={styles.badge}>Technical alpha · development</span>}
      </div>
      <button className={styles.menu} type="button" aria-expanded={open} aria-controls="primary-navigation"
        onClick={() => setOpen(!open)}>Menu</button>
      <nav id="primary-navigation" aria-label="Main navigation" className={open ? styles.open : styles.navigation}>
        {navigation.map(([path, name]) => <NavLink key={path} to={path} end={path === '/'}
          onClick={() => setOpen(false)}>{name}</NavLink>)}
      </nav>
      <p className={styles.footer}>Bookkeeping with clarity.</p>
    </aside>
    <div className={styles.content}>
      <header className={styles.topbar}><span>{navigation.find(([path]) => path === location.pathname
        || path !== '/' && location.pathname.startsWith(path + '/'))?.[1] ?? 'Page'}</span>
        <span className="muted">{session.entity.name}</span></header>
      <main id="main" tabIndex={-1} className={styles.main} key={location.key}><Outlet /></main>
    </div>
  </div>;
}
