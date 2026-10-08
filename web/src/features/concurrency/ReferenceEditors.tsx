import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, type Account, type Schemas } from '../../api/client';
import { accountQuery, resourceKey } from '../../api/query';
import { useEntity } from '../../app/context';
import { ProtectedEditor } from './ProtectedEditor';
import { RecordList } from './RecordList';
import { latest } from './mutations';
import { ActiveField, SelectField, TextField } from './Fields';

const options = (values: string[]) => values.map(value => ({ id: value, name: value }));
const metadata = (row: { id: string; baseline: string }) => ({ id: row.id, baseline: row.baseline });

function accountLoaded(row: Account) {
  const values: Schemas['AccountChanges'] = { name: row.name, type: row.type, classification: row.classification,
    opening_balance: row.opening_balance, active: row.active, parent_id: row.parent_id ?? '' };
  return { values, metadata: metadata(row) };
}

export function AccountEditor({ row, onClose }: { row: Account; onClose: () => void }) {
  const session = useEntity();
  const accounts = useQuery(accountQuery(session));
  return <ProtectedEditor session={session} loaded={accountLoaded(row)} title="Edit account" onClose={onClose}
    save={async (id, baseline, changes) => accountLoaded(await api.updateAccount(session, id, { baseline, changes }))}
    remove={(id, baseline) => api.deactivateAccount(session, id, baseline)} removeLabel="Deactivate"
    loadLatest={async id => accountLoaded(await latest(api.accounts, session, id))}
    fields={form => <><TextField form={form} name="name" label="Account name" />
      <SelectField form={form} name="type" label="Type" options={options(['Bank', 'Cash', 'Credit card', 'Short-term debt', 'Equity', 'Other'])} />
      <SelectField form={form} name="classification" label="Classification" options={options(['Asset', 'Liability', 'Equity'])} />
      <TextField form={form} name="opening_balance" label="Opening balance" />
      <p className="muted">Asset opening balances are normally positive. Liability and equity opening ledger balances are normally negative.</p>
      <SelectField form={form} name="parent_id" label="Parent account" options={[{ id: '', name: 'No parent' },
        ...(accounts.data?.items.filter(item => item.id !== row.id) ?? [])]} />
      <ActiveField form={form} name="active" /></>} />;
}

function categoryLoaded(row: Schemas['Category']) {
  const values: Schemas['CategoryChanges'] = { name: row.name, kind: row.kind, parent_id: row.parent_id ?? '' };
  return { values, metadata: metadata(row) };
}

function CategoryEditor({ row, onClose }: { row: Schemas['Category']; onClose: () => void }) {
  const session = useEntity();
  const categories = useQuery({ queryKey: resourceKey(session, 'categories'), queryFn: ({ signal }) => api.categories(session, signal) });
  return <ProtectedEditor session={session} loaded={categoryLoaded(row)} title="Edit category" onClose={onClose}
    save={async (id, baseline, changes) => categoryLoaded(await api.updateCategory(session, id, { baseline, changes }))}
    remove={(id, baseline) => api.deleteCategory(session, id, baseline)}
    loadLatest={async id => categoryLoaded(await latest(api.categories, session, id))}
    fields={form => <><TextField form={form} name="name" label="Category name" />
      <SelectField form={form} name="kind" label="Kind" options={options(['Income', 'Expense'])} />
      <SelectField form={form} name="parent_id" label="Parent category" options={[{ id: '', name: 'No parent' },
        ...(categories.data?.items.filter(item => item.id !== row.id) ?? [])]} /></>} />;
}

function managedLoaded(row: Schemas['ManagedReference']) {
  const values: Schemas['ManagedChanges'] = { name: row.name, active: row.active };
  return { values, metadata: metadata(row) };
}

function ManagedEditor({ row, resource, onClose }: { row: Schemas['ManagedReference']; resource: 'payees' | 'tags'; onClose: () => void }) {
  const session = useEntity();
  const list = resource === 'payees' ? api.payees : api.tags;
  const save = resource === 'payees' ? api.updatePayee : api.updateTag;
  const remove = resource === 'payees' ? api.removePayee : api.removeTag;
  return <ProtectedEditor session={session} loaded={managedLoaded(row)} title={resource === 'payees' ? 'Edit payee' : 'Edit tag'} onClose={onClose}
    save={async (id, baseline, changes) => managedLoaded(await save(session, id, { baseline, changes }))}
    remove={(id, baseline) => remove(session, id, baseline)}
    loadLatest={async id => managedLoaded(await latest(list, session, id))}
    fields={form => <><TextField form={form} name="name" label="Name" /><ActiveField form={form} name="active" /></>} />;
}

export function ReferencesPage({ resource }: { resource: 'categories' | 'payees' | 'tags' }) {
  const title = resource[0].toUpperCase() + resource.slice(1);
  return <><h1>{title}</h1><p className="lead">Review existing records and save changes for this business.</p>
    <nav aria-label="Reference data"><Link to="/categories">Categories</Link> · <Link to="/payees">Payees</Link> · <Link to="/tags">Tags</Link></nav>
    {resource === 'categories'
      ? <RecordList resource={resource} title="Categories" list={api.categories} label={row => row.name}
          editor={(row, close) => <CategoryEditor row={row} onClose={close} />} />
      : <><RecordList key={resource} resource={resource} title={title} list={resource === 'payees' ? api.payees : api.tags} label={row => row.name}
          editor={(row, close) => <ManagedEditor row={row} resource={resource} onClose={close} />} />
        <Link to={'/' + resource + '/merge'}>Merge {resource}</Link></>}
  </>;
}
