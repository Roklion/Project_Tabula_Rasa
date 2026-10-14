import { useContext, useEffect, useRef, useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useEntity } from './context';
import styles from './Shell.module.css';

import { entryRoutes, isEntryRoute, isReferenceRoute, matchesRoute, mileageRoutes, navigation, referenceRoutes } from './navigation';
import { WorkflowNav } from '../components/WorkflowNav';
import { EntitySelector } from './EntitySelection';
import { AuthContext } from './authContext';

export function Shell() {
  const session = useEntity();
  const auth = useContext(AuthContext);
  const location = useLocation();
  const workflowName = [...entryRoutes, ...referenceRoutes].find(route => matchesRoute(location.pathname, route.path))?.label;
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
        {navigation.map(([path, name]) => <Link key={path} to={path} aria-current={location.pathname === path || path !== '/' && matchesRoute(location.pathname, path) ? 'page'
          : path === '/transactions' && isEntryRoute(location.pathname) || path === '/categories' && isReferenceRoute(location.pathname) ? 'true' : undefined}>{name}</Link>)}
      </nav>
      <p className={styles.footer}>Bookkeeping with clarity.</p>
      {!session.trusted_development && <button onClick={auth.logout}>Sign out</button>}
    </aside>
    <div className={styles.content}>
      <header className={styles.topbar}><span>{workflowName ?? navigation.find(([path]) => matchesRoute(location.pathname, path))?.[1] ?? 'Page'}</span>
        <span className="muted">{session.entity.name}</span></header>
      <main ref={main} id="main" tabIndex={-1} className={styles.main} key={location.key}>{isEntryRoute(location.pathname) ? <WorkflowNav label="Entries" routes={entryRoutes} canWrite={session.capabilities.includes('bookkeeping:write')} />
        : matchesRoute(location.pathname, '/mileage') ? <WorkflowNav label="Mileage workflows" routes={mileageRoutes} canWrite={session.capabilities.includes('bookkeeping:write')} />
          : isReferenceRoute(location.pathname) ? <WorkflowNav label="Reference data" routes={referenceRoutes} canWrite={session.capabilities.includes('bookkeeping:write')} /> : null}
        <Outlet /></main>
    </div>
  </div>;
}
