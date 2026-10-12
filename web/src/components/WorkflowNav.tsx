import { Link, matchPath, useLocation } from 'react-router-dom';

export type WorkflowRoute = { path: string; label: string; write?: boolean };

/** Links retain router blocking and native keyboard behavior; these are routes, not tabs. */
export function WorkflowNav({ label, routes, canWrite }: { label: string; routes: readonly WorkflowRoute[]; canWrite: boolean }) {
  const { pathname } = useLocation();
  const visible = routes.filter(route => !route.write || canWrite);
  // A detail route belongs to its list; a more specific create route takes precedence.
  const current = visible.filter(route => matchPath({ path: route.path, end: false }, pathname))
    .sort((a, b) => b.path.length - a.path.length)[0]?.path;
  return <nav className="workflowNav" aria-label={label}><ul>
    {visible.map(route => <li key={route.path}>
      <Link to={route.path} aria-current={route.path === current ? 'page' : undefined}>{route.label}</Link>
    </li>)}
  </ul></nav>;
}
