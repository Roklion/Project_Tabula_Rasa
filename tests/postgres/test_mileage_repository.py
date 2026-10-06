"""Native mileage service behavior, atomic imports and loaded-record isolation."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from sqlalchemy import text

from tabula_rasa.application.mileage import MileageValidationError, prepare_mileage_trip
from tabula_rasa.errors import StorageConflictError, StorageValidationError
from tabula_rasa.infrastructure.postgres.mileage import PostgresMileageRepository
from tests.postgres.core_support import seed_core


def trip(**changes):
    return {**dict(trip_date='2026-10-05', miles='12.34', vehicle='Car',
                   start_location='Office', destination='Client', business_purpose='Meeting'), **changes}


def source(**changes):
    return {**dict(Date='10/05/2026', Type='Business', Vehicle='Car', Distance='12.3',
                   **{'Trip Purpose': 'Meeting', 'Start Address': 'Office', 'End Address': 'Client'}), **changes}


def test_mileage_crud_round_trip_tag_history_and_order(database):
    alpha, beta = seed_core(database)
    outbound, returned = alpha.mileage.create_round_trip(**trip(), new_tag_name='Job')
    assert outbound.miles == returned.miles == '12.3'
    assert returned.start_location == outbound.destination
    assert [item.id for item in alpha.mileage.list_trips()] == [returned.id, outbound.id]
    assert outbound.tags == ('Job',) and len(outbound.tag_ids) == 1
    assert beta.mileage.list_trips() == ()
    assert alpha.mileage.list_trips(start='2026-10-06') == ()
    alpha.tags.update(outbound.tag_ids[0], active=False)
    edited = alpha.mileage.edit_trip(outbound.id, expected=outbound.as_record(), notes='Changed')
    assert edited.created_at == outbound.created_at and edited.tag_ids == outbound.tag_ids
    assert edited.baseline != outbound.baseline
    assert [item.id for item in alpha.mileage.list_trips()] == [returned.id, outbound.id]
    with pytest.raises(StorageConflictError):
        alpha.mileage.delete_trip(outbound.id, expected={'baseline': outbound.baseline})
    with pytest.raises(MileageValidationError, match='inactive'):
        alpha.mileage.create_trip(**trip(), tag_ids=list(outbound.tag_ids))
    alpha.mileage.delete_trip(outbound.id, expected={'baseline': edited.baseline})
    assert [item.id for item in alpha.mileage.list_trips()] == [returned.id]
    assert alpha.transactions.list() == []


def test_mileage_overlapping_ids_and_baseline_lifetimes(database):
    alpha, beta = seed_core(database)
    repositories = {scope: PostgresMileageRepository(database, scope) for scope in ('alpha', 'beta')}
    loaded = {}
    for scope, repo in repositories.items():
        loaded[scope] = repo.add_trips(lambda tags, create: [prepare_mileage_trip(trip(), tags, trip_id='same')])[0]
    with pytest.raises(StorageConflictError):
        alpha.mileage.edit_trip('same', expected={'baseline': loaded['beta'].baseline}, notes='Foreign')
    alpha.mileage.delete_trip('same', expected=loaded['alpha'].as_record())
    replacement = repositories['alpha'].add_trips(
        lambda tags, create: [prepare_mileage_trip(trip(), tags, trip_id='same')])[0]
    with pytest.raises(StorageConflictError):
        alpha.mileage.delete_trip('same', expected={'baseline': loaded['alpha'].baseline})
    assert beta.mileage.list_trips()[0] == loaded['beta']
    assert alpha.mileage.list_trips()[0] == replacement
    foreign = beta.tags.create('Foreign')
    with pytest.raises(MileageValidationError, match='does not exist'):
        alpha.mileage.create_trip(**trip(), tag_ids=[foreign['id']])


def test_mileage_inline_reactivation_and_late_failure_roll_back(database, monkeypatch):
    alpha, _ = seed_core(database)
    inactive = alpha.tags.create('Job')
    alpha.tags.update(inactive['id'], active=False)
    made = alpha.mileage.create_trip(**trip(), new_tag_name='job')
    assert made.tag_ids == (inactive['id'],)
    repository = PostgresMileageRepository(database, 'alpha')
    original = repository.write
    calls = []

    def late_failure(connection, item, **options):
        result = original(connection, item, **options)
        calls.append(item.id)
        if len(calls) == 2:
            connection.execute(text("UPDATE mileage_records SET miles=0 WHERE entity_id='alpha'"))
        return result

    monkeypatch.setattr(repository, 'write', late_failure)

    def prepare(tags, create):
        tag = create('Rolled back')
        return [replace(prepare_mileage_trip(trip(), tags), tag_ids=(tag.id,)) for _ in range(2)]

    with pytest.raises(StorageValidationError) as failure:
        repository.add_trips(prepare)
    assert failure.value.code == 'invariant' and failure.value.__context__ is None
    assert len(alpha.mileage.list_trips()) == 1
    assert [item['name'] for item in alpha.tags.list()] == ['Job']


def test_mileage_import_duplicate_history_errors_and_concurrent_retry(database):
    alpha, beta = seed_core(database)
    rows = [source(), source(), source(Type='Personal')]
    preview = alpha.mileage.preview_quickbooks_mileage(rows)
    assert preview.summary == dict(ready=1, duplicates=1, personal_skipped=1, unreviewed_skipped=0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: alpha.mileage.import_quickbooks_mileage(rows), range(2)))
    assert sorted(map(len, results)) == [0, 1]
    imported = alpha.mileage.list_trips()[0]
    alpha.mileage.edit_trip(imported.id, notes='Changed after import', business_purpose='Different')
    assert alpha.mileage.import_quickbooks_mileage(rows) == ()
    assert len(beta.mileage.import_quickbooks_mileage(rows)) == 1
    with pytest.raises(MileageValidationError):
        beta.mileage.import_quickbooks_mileage([source(Date='invalid')])
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM import_records WHERE entity_id='alpha'")) == 1
        assert connection.scalar(text("SELECT count(*) FROM entries")) == 0
        provenance = connection.execute(text(
            "SELECT source_position,record_kind,mileage_id FROM import_records WHERE entity_id='alpha'"
        )).one()
        assert tuple(provenance) == (1, 'mileage', imported.id)
    assert len(beta.mileage.list_trips()) == 1
