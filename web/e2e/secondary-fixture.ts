export const longName = 'Synthetic business label with deliberately long words for responsive fields and management records';
export const longId = 'synthetic-record-identity-with-long-stable-provenance-0123456789';
export const session = { actor_id: 'synthetic', organization_id: 'synthetic', entity: { id: 'alpha', name: 'Alpha demonstration' },
  capabilities: ['bookkeeping:read', 'bookkeeping:write', 'bookkeeping:import'], cache_scope: 'forms-secondary-alpha', csrf_token: 'synthetic', trusted_development: true };
export const account = { id: 'account', name: longName, type: 'Bank', classification: 'Asset', opening_balance: '0.00', parent_id: null, active: true, baseline: 'loaded-account' };
export const accumulated = { ...account, id: 'accumulated', name: 'Accumulated depreciation', type: 'Other' };
export const category = { id: 'category', name: 'Synthetic expense category with a long descriptive label', kind: 'Expense', parent_id: null, baseline: 'loaded-category' };
export const references = [{ id: 'reference', name: longName, active: true, baseline: 'loaded-reference' },
  { id: 'source', name: 'Second synthetic source with another long descriptive name', active: true, baseline: 'loaded-source' }];
export const transaction = { id: 'transaction', txn_date: '2026-10-07', kind: 'Expense', amount: '1234.56', account_id: 'account', to_account_id: '',
  category_id: 'category', payee_id: 'reference', tag_ids: ['reference'], description: longName, reference: 'Synthetic reference',
  source_type: '', baseline: 'loaded-transaction' };
export const mixed = { ...transaction, id: 'mixed', total_expense: '1234.56', business_use_percentage: '60', allocated_amount: '740.74',
  allocation_rationale: 'Synthetic allocation rationale spanning several words and lines in a narrow viewport.', linked_transaction_id: longId,
  ledger_status: 'linked', recurring_schedule_id: '', recurring_scheduled_date: '', recurring_occurrence_type: '', baseline: 'loaded-mixed' };
export const recurring = { ...transaction, id: 'recurring', name: longName, source_kind: 'transaction', start_date: '2026-10-01', end_date: '',
  recurrence_unit: 'month', recurrence_interval: '1', total_expense: '', business_use_percentage: '100', allocation_rationale: '', status: 'active',
  next_due_date: '2026-11-01', latest_current_occurrence_date: '2026-10-01', attention_message: '', baseline: 'loaded-recurring' };
export const asset = { id: 'asset', name: longName, asset_type: 'Equipment', notes: 'Synthetic multiline notes.\nA second line preserves useful context.',
  acquisition_date: '2026-01-01', depreciation_start_date: '2026-01-01', cost_basis: '12345.67', salvage_value: '0.00', useful_life_quarters: '4',
  depreciation_expense_account_id: 'category', accumulated_depreciation_account_id: 'accumulated', payee_id: 'reference', tag_ids: ['reference'],
  reference: 'Synthetic reference', source_transaction_id: longId, status: 'active', retired_date: '', depreciation_method: 'straight_line', baseline: 'loaded-asset' };
export const assetDetail = { asset, terms_locked: true, posting_accounts_locked: true, can_delete: false,
  schedule: [{ sequence: 1, scheduled_date: '2026-03-31', depreciation_amount: '3086.42', cumulative_depreciation: '3086.42', remaining_book_value: '9259.25',
    override_reason: 'Synthetic override reason with enough words to wrap.', posting_status: 'Posted', journal_entry_id: longId }], history: [{ id: 'posted' }] };
export const mileage = { id: 'mileage', trip_date: '2026-10-07', miles: '123.4', vehicle: 'Synthetic vehicle', start_location: longName,
  destination: 'Synthetic destination with a long address and business name', business_purpose: 'Visit the synthetic demonstration business for a scheduled appointment.',
  notes: 'Synthetic trip notes.\nSecond line for a narrow screen.', tag_ids: ['reference'], baseline: 'loaded-mileage' };
export const receipt = { id: longId, filename: 'synthetic-receipt-with-a-deliberately-long-filename-for-narrow-screens-0123456789.pdf', mime_type: 'application/pdf', byte_size: 1234, sha256: 'a'.repeat(64) };

export function secondaryResponse(url: URL, capabilities = session.capabilities) {
    const path = url.pathname;
    // Every request stays intercepted. Unmatched reads are empty synthetic lists;
    // mutation tests below replace only the endpoint they explicitly exercise.
    const json = path.endsWith('/session') ? { ...session, capabilities } : path === '/api/v1/entities' ? { items: [session.entity] }
      : path.endsWith('/accounts') ? { items: [account, accumulated] } : path.endsWith('/categories') ? { items: [category] }
        : path.endsWith('/payees') || path.endsWith('/tags') ? { items: references } : path.endsWith('/transactions') ? { items: [transaction] }
          : path.endsWith('/mixed-use/mixed/copy-draft') ? { ...mixed, source_id: 'synthetic-copy-source', linked_transaction_id: 'synthetic-copy-projection', new_payee_name: '', new_tag_name: '' }
          : path.endsWith('/mixed-use/allocation') ? { allocated_amount: '740.74' } : path.endsWith('/mixed-use/mixed') ? mixed : path.endsWith('/mixed-use') ? { items: [mixed] }
            : path.endsWith('/recurring/recurring') ? { schedule: recurring, occurrences: [{ ...transaction, id: longId, recurring_occurrence_type: 'initial', recurring_scheduled_date: '2026-10-01', source_id: '' }] }
              : path.endsWith('/recurring') ? { items: [recurring] } : path.endsWith('/assets/types') ? { items: ['Equipment'] }
                : path.endsWith('/assets/asset') ? assetDetail : path.endsWith('/assets') ? { items: [asset] }
                  : path.endsWith('/mileage/maps') ? { browser_api_key: null, region_code: null, routes_available: false }
                  : path.endsWith('/mileage/mileage') ? mileage : path.endsWith('/mileage') ? { items: [mileage] }
                    : path.endsWith('/receipts') ? { items: [receipt] } : path.endsWith('/documents') ? { items: [{ ...receipt, id: 'unreferenced', filename: 'synthetic-unreferenced.pdf' }], needing_integrity: 0 }
                      : { items: [] };
    return json;
}
