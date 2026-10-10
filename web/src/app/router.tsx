import { createBrowserRouter, createMemoryRouter } from 'react-router-dom';
import { ContextBoundary } from './ContextBoundary';
import { Shell } from './Shell';
import { navigation } from './navigation';
import { Accounts, PlannedPage, MissingPage, RouteError } from '../features/foundation/Pages';
import { ReferencesPage } from '../features/concurrency/ReferenceEditors';
import { BookkeepingPage } from '../features/concurrency/BookkeepingEditors';
import { ManagedMergeForm } from '../features/concurrency/ManagedMergeForm';
import { MileageDetail, MileagePage, NewMileage } from '../features/mileage/MileagePage';
import { ReceiptsPage } from '../features/documents/ReceiptsPage';
import { ReferenceCreator } from '../features/workflows/ReferenceCreators';
import { EntryCreator } from '../features/workflows/EntryCreators';
import { LedgerPage } from '../features/workflows/LedgerPage';
import { ReportsPage } from '../features/workflows/ReportsPage';

const routes = [{
  element: <ContextBoundary><Shell /></ContextBoundary>,
  errorElement: <RouteError />,
  children: [
    { index: true, element: <ReportsPage dashboard /> },
    { path: 'accounts', element: <Accounts /> },
    { path: 'transactions', element: <LedgerPage /> },
    { path: 'reports', element: <ReportsPage /> },
    ...(['accounts', 'categories', 'payees', 'tags'] as const).map(resource => ({ path: resource + '/new', element: <ReferenceCreator key={resource} resource={resource} /> })),
    ...(['transactions', 'journals'] as const).map(resource => ({ path: resource + '/new', element: <EntryCreator key={resource} resource={resource} /> })),
    ...(['categories', 'payees', 'tags'] as const).map(resource => ({ path: resource, element: <ReferencesPage resource={resource} /> })),
    { path: 'journals', element: <BookkeepingPage resource="journals" /> },
    { path: 'mileage', element: <MileagePage /> },
    { path: 'mileage/new', element: <NewMileage /> },
    { path: 'mileage/:recordId', element: <MileageDetail /> },
    { path: 'transactions/:recordId/receipts', element: <ReceiptsPage /> },
    ...(['payees', 'tags'] as const).map(resource => ({ path: resource + '/merge', element: <><h1>Merge {resource}</h1><ManagedMergeForm key={resource} resource={resource} /></> })),
    ...navigation.filter(([path]) => !['/', '/accounts', '/categories', '/transactions', '/mileage', '/reports'].includes(path)).map(([path, name]) => ({
      path: path.slice(1), element: <PlannedPage title={name} />,
    })),
    { path: '*', element: <MissingPage /> },
  ],
}];

export const createAppRouter = () => createBrowserRouter(routes);
export const createTestRouter = (initialEntries: string[] = ['/']) => createMemoryRouter(routes, { initialEntries });
