export const session = {
  actor_id: 'synthetic', organization_id: 'synthetic', entity: { id: 'alpha', name: 'Alpha demonstration' },
  capabilities: ['bookkeeping:read', 'bookkeeping:write', 'bookkeeping:import'], cache_scope: 'core-alpha', csrf_token: 'synthetic', trusted_development: true,
};
export const longName = 'Operating account with a deliberately long synthetic label for field and table wrapping';
export const account = { id: 'account', name: longName, type: 'Bank', classification: 'Asset', opening_balance: '0.00', parent_id: null, active: true, baseline: 'synthetic' };
export const report = {
  profit_loss: { income: '1250.00', expenses: '1400.25', net: '-150.25' },
  balance_sheet: { assets: [{ id: 'account', name: longName, direct_balance: '999999999999.99', rollup_balance: '999999999999.99' }],
    liabilities: [], equity: [], current_earnings: '-150.25', total_assets: '999999999999.99', total_liabilities: '0.00', total_equity: '999999999999.99', difference: '0.00' },
  account_balances: [{ id: 'account', name: longName, classification: 'Asset', active: true, balance: '999999999999.99' }],
};
export const ordinary = { id: 'ordinary', record_id: 'ordinary', entry_type: 'transaction', txn_date: '2026-10-07', kind: 'Expense', account: longName,
  to_account: '', category: 'Office', payee: 'Synthetic supplier', amount: '19.25', tags: ['Long synthetic tag for responsive selection'],
  description: 'Synthetic ordinary entry', reference: 'demo-reference', receipt_count: 1, source_type: '', postings: [] };
export const journal = { ...ordinary, id: 'journal:entry', record_id: 'entry', entry_type: 'journal', txn_date: '2026-10-06', kind: 'Journal',
  account: 'Multiple accounts / 2 postings', amount: '40.00', category: '', payee: '', tags: [], description: 'Complete synthetic journal', receipt_count: 0,
  postings: [{ target: longName, side: 'Debit', amount: '40.00', payee: '', description: 'Needle posting' },
    { target: 'Equity', side: 'Credit', amount: '40.00', payee: '', description: 'Sibling retained' }] };
export const owned = { ...ordinary, id: 'mixed', record_id: 'mixed', source_type: 'mixed_use_expense', description: 'Source-owned synthetic expense', amount: '0.00' };

export function coreResponse(url: URL) {
    const path = url.pathname;
    const items = [ordinary, journal, owned].filter(row =>
      (!url.searchParams.get('start') || row.txn_date >= url.searchParams.get('start')!)
      && (!url.searchParams.get('end') || row.txn_date <= url.searchParams.get('end')!)
      && (!url.searchParams.get('kind') || url.searchParams.get('kind') === 'All' || row.kind === url.searchParams.get('kind'))
      && (!url.searchParams.has('tag_ids') || row.tags.some(tag => tag === ordinary.tags[0])));

    const json = path.endsWith('/session') ? session : path === '/api/v1/businesses' ? { items: [session.entity] }
      : path.endsWith('/reports/summary') ? report : path.endsWith('/ledger') ? { items }
        : { items: path.endsWith('/accounts') ? [account] : path.endsWith('/tags') ? [{ id: 'tag', name: ordinary.tags[0], active: true, baseline: 'synthetic' }] : [] };
    return json;
}
