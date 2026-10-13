"""Existing QuickBooks mileage workflow through the scoped HTTP/service stack."""

from dataclasses import replace
from unittest.mock import patch

from tabula_rasa.application.mileage import MileageService
from tabula_rasa.errors import StorageError
from tabula_rasa.infrastructure.postgres.mileage import PostgresMileageRepository
from tests.postgres.test_http_baselines import commercial as commercial, HEADERS, PREFIX, snapshot

PATH = PREFIX + 'imports/quickbooks-mileage'
UPLOAD_HEADERS = {**HEADERS, 'Content-Type': 'application/octet-stream'}
CSV = (b'Date,Type,Trip Purpose,Vehicle,Start Address,End Address,Distance\n'
       b'10/08/2026,Business,Inspection,Van,Office,Site,12.36\n'
       b'10/08/2026,Business,Inspection,Van,Office,Site,12.36\n'
       b'10/09/2026,Personal,Shopping,Car,Home,Shop,3\n'
       b'10/09/2026,Unreviewed,Meeting,Car,Home,Client,5\n')


def test_preview_confirmed_import_duplicate_and_two_entity_isolation(database, commercial):
    alpha, beta, (client, _), _ = commercial
    before = snapshot(database)
    response = client.post(PATH + '/preview', headers=UPLOAD_HEADERS, content=CSV)
    assert response.status_code == 200
    preview = response.json()
    assert preview['summary'] == dict(ready=1, duplicates=1, personal_skipped=1, unreviewed_skipped=1)
    assert preview['duplicate_rows'] == [3] and preview['personal_rows'] == [4] and preview['unreviewed_rows'] == [5]
    assert preview['rows'][0]['miles'] == '12.4'
    assert len(preview['source_rows']) == 4
    assert snapshot(database) == before
    assert client.post(PATH, headers=HEADERS, content=CSV).status_code == 422
    assert client.post(PATH, content=CSV).status_code == 403
    assert client.post(PATH.replace('/alpha/', '/beta/'), headers=UPLOAD_HEADERS, content=CSV).status_code == 403
    committed = client.post(PATH, headers=UPLOAD_HEADERS, content=CSV)
    assert committed.status_code == 200 and committed.json()['imported'] == 1
    identity = committed.json()['ids'][0]
    assert next(trip for trip in alpha.mileage.list_trips() if trip.id == identity).miles == '12.4'
    assert beta.mileage.list_trips() == ()
    assert snapshot(database)['entries'] == before['entries']
    assert client.post(PATH, headers=UPLOAD_HEADERS, content=CSV).json() == dict(imported=0, ids=[])
    assert client.post(PATH + '/preview', headers=UPLOAD_HEADERS, content=CSV).json()['summary']['duplicates'] == 2
    context = client.app.state.runtime.resolve_context(None)
    client.app.state.runtime.resolve_context = lambda request: replace(context, entity_id='beta', cache_scope='beta-scope')
    beta_path = PATH.replace('/alpha/', '/beta/')
    assert client.post(beta_path + '/preview', headers=UPLOAD_HEADERS, content=CSV).json()['summary']['ready'] == 1
    beta_result = client.post(beta_path, headers=UPLOAD_HEADERS, content=CSV).json()
    assert beta_result['imported'] == 1 and beta_result['ids'] != [identity]
    assert len(beta.mileage.list_trips()) == 1
    assert len(alpha.mileage.list_trips()) == 2  # Original fixture plus import.


def test_invalid_rows_reject_batch_and_failed_write_rolls_back(database, commercial):
    _, _, (client, _), _ = commercial
    invalid = CSV + b'10/10/2026,Business,Inspection,Van,Office,Site,invalid\n'
    before = snapshot(database)
    preview = client.post(PATH + '/preview', headers=UPLOAD_HEADERS, content=invalid).json()
    assert preview['summary']['ready'] == 1 and len(preview['errors']) == 1
    assert 'row 6' in preview['errors'][0]
    assert client.post(PATH, headers=UPLOAD_HEADERS, content=invalid).status_code == 422
    assert snapshot(database) == before
    assert client.post(PATH, headers=UPLOAD_HEADERS, content=b'Date,Distance\n2026-10-08,10\n').status_code == 422
    assert client.post(PATH + '/preview', headers=UPLOAD_HEADERS, content=b'\xff\xfe').status_code == 422
    second = CSV + b'10/10/2026,Business,Second inspection,Van,Office,Second site,20\n'
    original_write = PostgresMileageRepository.write
    writes = []

    def fail_second(repository, connection, trip, **kwargs):
        writes.append(trip.id)
        if len(writes) == 2:
            raise StorageError('Synthetic unavailable')
        return original_write(repository, connection, trip, **kwargs)

    with patch.object(PostgresMileageRepository, 'write', fail_second):
        failed = client.post(PATH, headers=UPLOAD_HEADERS, content=second)
    assert failed.status_code == 503 and snapshot(database) == before
    assert client.post(PATH, headers=UPLOAD_HEADERS, content=second).json()['imported'] == 2


def test_lost_success_response_explicit_retry_does_not_duplicate(database, commercial):
    alpha, _, (client, _), _ = commercial
    original_import = MileageService.import_quickbooks_mileage

    def lost_response(service, rows):
        original_import(service, rows)
        raise StorageError('Synthetic response lost after commit')

    with patch.object(MileageService, 'import_quickbooks_mileage', lost_response):
        assert client.post(PATH, headers=UPLOAD_HEADERS, content=CSV).status_code == 503
    saved = snapshot(database)
    assert len(alpha.mileage.list_trips()) == 2
    assert client.post(PATH + '/preview', headers=UPLOAD_HEADERS, content=CSV).json()['summary']['ready'] == 0
    assert client.post(PATH, headers=UPLOAD_HEADERS, content=CSV).json() == dict(imported=0, ids=[])
    assert snapshot(database) == saved
