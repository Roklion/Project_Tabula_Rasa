import { createBrowserRouter, createMemoryRouter } from 'react-router-dom';
import { ContextBoundary } from './ContextBoundary';
import { Shell } from './Shell';
import { navigation } from './navigation';
import { Dashboard, Accounts, PlannedPage, MissingPage, RouteError } from '../features/foundation/Pages';

const routes = [{
  element: <ContextBoundary><Shell /></ContextBoundary>,
  errorElement: <RouteError />,
  children: [
    { index: true, element: <Dashboard /> },
    { path: 'accounts', element: <Accounts /> },
    ...navigation.filter(([path]) => path !== '/' && path !== '/accounts').map(([path, name]) => ({
      path: path.slice(1), element: <PlannedPage title={name} />,
    })),
    { path: '*', element: <MissingPage /> },
  ],
}];

export const createAppRouter = () => createBrowserRouter(routes);
export const createTestRouter = (initialEntries: string[] = ['/']) => createMemoryRouter(routes, { initialEntries });
