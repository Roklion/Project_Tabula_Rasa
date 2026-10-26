"""Mixed-use copies preserve shared preparation and active PostgreSQL associations."""

from tests.postgres.test_secondary_service_contracts import secondary_services as secondary_services


def test_mixed_copy_snapshot_survives_original_changes_and_uses_current_allocation(secondary_services):
    services = secondary_services
    account = services.accounts.create('Checking', 'Bank')['id']
    category = services.categories.create('Office', 'Expense')['id']
    payee = services.payees.create('Vendor')['id']
    tag = services.tags.create('Job')['id']
    source = services.mixed_use.create(source_id='source', linked_transaction_id='projection',
                                      txn_date='2026-01-31', account_id=account, category_id=category,
                                      total_expense='100', business_use_percentage='50', allocation_rationale='Business use',
                                      payee_id=payee, tag_ids=[tag], description='Original memo. Copy From old')
    draft = services.mixed_use.copy_draft('source')
    assert draft['description'] == 'Original memo. Copy From source'
    assert draft['payee_id'] == payee and draft['tag_ids'] == [tag]
    assert not set(draft) & {'receipt_references', 'baseline', 'recurring_schedule_id', 'recurring_occurrence_type'}
    assert len({draft['source_id'], draft['linked_transaction_id'], source['id'], source['linked_transaction_id']}) == 4
    services.mixed_use.delete('source', expected_source=source)
    copied = services.mixed_use.create(**{**draft, 'total_expense': '19.99', 'business_use_percentage': '50',
                                        'description': 'Corrected memo. Copy From previous'})
    assert copied['allocated_amount'] == '10.00'
    assert copied['description'] == 'Corrected memo. Copy From source'
    assert copied['receipt_references'] in ([], '[]')
    assert services.mixed_use.list()[0]['id'] == draft['source_id']
    services.payees.update(payee, active=False)
    services.tags.update(tag, active=False)
    second = services.mixed_use.copy_draft(copied['id'])
    assert second['payee_id'] == '' and second['tag_ids'] == []
