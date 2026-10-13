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
import { AssetsPage, AssetDetail, NewAsset } from '../features/secondary/AssetsPage';
import { MixedUsePage, MixedUseDetail, NewMixedUse } from '../features/secondary/MixedUsePage';
import { RecurringPage, RecurringDetail, NewRecurring } from '../features/secondary/RecurringPage';
import { PageHeader } from '../components/VisualPrimitives';

const routes = [{
  element: <ContextBoundary><Shell /></ContextBoundary>,
  errorElement: <RouteError />,
  children: [
    { index: true, element: <ReportsPage dashboard /> },
    { path: 'accounts', element: <Accounts /> },
    { path: 'transactions', element: <LedgerPage /> },
    { path: 'reports', element: <ReportsPage /> },
    { path: 'assets', element: <AssetsPage /> },
    { path: 'assets/new', element: <NewAsset /> },
    { path: 'assets/:recordId', element: <AssetDetail /> },
    { path: 'mixed-use', element: <MixedUsePage /> },
    { path: 'mixed-use/new', element: <NewMixedUse /> },
    { path: 'mixed-use/:recordId', element: <MixedUseDetail /> },
    { path: 'recurring', element: <RecurringPage /> },
    { path: 'recurring/new', element: <NewRecurring /> },
    { path: 'recurring/:recordId', element: <RecurringDetail /> },
    ...(['accounts', 'categories', 'payees', 'tags'] as const).map(resource => ({ path: resource + '/new', element: <ReferenceCreator key={resource} resource={resource} /> })),
    ...(['transactions', 'journals'] as const).map(resource => ({ path: resource + '/new', element: <EntryCreator key={resource} resource={resource} /> })),
    ...(['categories', 'payees', 'tags'] as const).map(resource => ({ path: resource, element: <ReferencesPage resource={resource} /> })),
    { path: 'journals', element: <BookkeepingPage resource="journals" /> },
    { path: 'mileage', element: <MileagePage /> },
    { path: 'mileage/new', element: <NewMileage /> },
    { path: 'mileage/:recordId', element: <MileageDetail /> },
    { path: 'transactions/:recordId/receipts', element: <ReceiptsPage /> },
    ...(['payees', 'tags'] as const).map(resource => ({ path: resource + '/merge', element: <><PageHeader title={'Merge ' + resource} description="Move references into one retained active record for this business." /><ManagedMergeForm key={resource} resource={resource} /></> })),
    ...navigation.filter(([path]) => !['/', '/accounts', '/categories', '/transactions', '/mileage', '/reports', '/assets'].includes(path)).map(([path, name]) => ({
      path: path.slice(1), element: <PlannedPage title={name} />,
    })),
    { path: '*', element: <MissingPage /> },
  ],
}];

export const createAppRouter = () => createBrowserRouter(routes);
export const createTestRouter = (initialEntries: string[] = ['/']) => createMemoryRouter(routes, { initialEntries });
