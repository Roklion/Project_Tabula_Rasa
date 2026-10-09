import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useEntity } from './context';
import styles from './Shell.module.css';

import { navigation } from './navigation';
import { EntitySelector } from './EntitySelection';

export function Shell() {
  const session = useEntity();
  const location = useLocation();
  const [menu, setMenu] = useState({ location, open: false });
  // Reset on each successful navigation, including Back to a previous entry.
  // A blocked navigation retains its location and the initiating link.
  if (menu.location !== location) setMenu({ location, open: false });
  const open = menu.location === location && menu.open;
  const main = useRef<HTMLElement>(null);
  const previousPath = useRef(location.pathname);
  useEffect(() => {
    if (previousPath.current !== location.pathname) main.current?.focus();
    previousPath.current = location.pathname;
  }, [location.pathname]);
  return <div className={styles.shell} onClickCapture={event => {
    // Safari does not focus pointer-activated links; retain the actual opener
    // for a blocked navigation's shared confirmation.
    if (event.target instanceof Element) event.target.closest<HTMLAnchorElement>('a[href]')?.focus();
  }}>
    <a className={styles.skip} href="#main">Skip to content</a>
    <aside className={styles.sidebar}>
      <div className={styles.brand}>Project <br />Tabula Rasa</div>
      <div className={styles.context}><span className="muted">Business</span>
        <strong>{session.entity.name}</strong>
        {session.trusted_development && <EntitySelector activeId={session.entity.id} />}
        {session.trusted_development && <span className={styles.badge}>Technical alpha · development</span>}
      </div>
      <button className={styles.menu} type="button" aria-expanded={open} aria-controls="primary-navigation"
        onClick={() => setMenu({ location, open: !open })}>Menu</button>
      <nav id="primary-navigation" aria-label="Main navigation" className={open ? styles.open : styles.navigation}>
        {navigation.map(([path, name]) => <NavLink key={path} to={path} end={path === '/'}>{name}</NavLink>)}
      </nav>
      <p className={styles.footer}>Bookkeeping with clarity.</p>
    </aside>
    <div className={styles.content}>
      <header className={styles.topbar}><span>{navigation.find(([path]) => path === location.pathname)?.[1] ?? 'Page'}</span>
        <span className="muted">{session.entity.name}</span></header>
      <main ref={main} id="main" tabIndex={-1} className={styles.main} key={location.key}><Outlet /></main>
    </div>
  </div>;
}
