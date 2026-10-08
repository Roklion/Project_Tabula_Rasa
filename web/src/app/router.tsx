import { createBrowserRouter, createMemoryRouter } from 'react-router-dom';
import { ContextBoundary } from './ContextBoundary';
import { Shell } from './Shell';
import { navigation } from './navigation';
import { Dashboard, Accounts, PlannedPage, MissingPage, RouteError } from '../features/foundation/Pages';
import { ReferencesPage } from '../features/concurrency/ReferenceEditors';
import { BookkeepingPage } from '../features/concurrency/BookkeepingEditors';
import { ManagedMergeForm } from '../features/concurrency/ManagedMergeForm';

const routes = [{
  element: <ContextBoundary><Shell /></ContextBoundary>,
  errorElement: <RouteError />,
  children: [
    { index: true, element: <Dashboard /> },
    { path: 'accounts', element: <Accounts /> },
    ...(['categories', 'payees', 'tags'] as const).map(resource => ({ path: resource, element: <ReferencesPage resource={resource} /> })),
    ...(['transactions', 'journals', 'mileage'] as const).map(resource => ({ path: resource, element: <BookkeepingPage resource={resource} /> })),
    ...(['payees', 'tags'] as const).map(resource => ({ path: resource + '/merge', element: <><h1>Merge {resource}</h1><ManagedMergeForm key={resource} resource={resource} /></> })),
    ...navigation.filter(([path]) => !['/', '/accounts', '/categories', '/transactions', '/mileage'].includes(path)).map(([path, name]) => ({
      path: path.slice(1), element: <PlannedPage title={name} />,
    })),
    { path: '*', element: <MissingPage /> },
  ],
}];

export const createAppRouter = () => createBrowserRouter(routes);
export const createTestRouter = (initialEntries: string[] = ['/']) => createMemoryRouter(routes, { initialEntries });
