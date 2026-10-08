from tabula_rasa.application.baselines import RecordBaseline
from tabula_rasa.http.app import create_app
from tests.http.test_transport import RECORD, client as client, runtime as runtime

TOKEN = RecordBaseline('alpha', 'account', 'account-1', 'incarnation', 1).encode()
CHANGES = {key: RECORD[key] for key in ('name', 'type', 'classification', 'opening_balance', 'active', 'parent_id')}
HEADERS = {'Origin': 'http://testserver', 'X-CSRF-Token': 'test-csrf'}


def test_update_passes_original_token_without_reading_a_replacement(client, runtime):
    runtime.accounts.update.return_value = {**RECORD, 'baseline': TOKEN}
    response = client.patch('/api/v1/entities/alpha/accounts/account-1', headers=HEADERS,
        json={'baseline': TOKEN, 'changes': CHANGES})
    assert response.status_code == 200
    runtime.accounts.update.assert_called_once_with('account-1', expected={'baseline': TOKEN}, **CHANGES)
    runtime.accounts.list.assert_not_called()


def test_missing_or_invalid_baselines_never_reach_service_composition(client, runtime):
    for token, code in [(None, 'baseline_required'), ('', 'baseline_required'), (False, 'baseline_invalid'),
                        ('private-malformed-token', 'baseline_invalid')]:
        response = client.patch('/api/v1/entities/alpha/accounts/account-1', headers=HEADERS,
            json={'baseline': token, 'changes': CHANGES})
        assert response.status_code == 422 and response.json()['error']['code'] == code
        assert 'private-malformed-token' not in response.text
    runtime.services.assert_not_called()
    runtime.accounts.update.assert_not_called()


def test_generated_mutation_contracts_require_loaded_metadata():
    schema = create_app(schema_only=True).openapi()
    components = schema['components']['schemas']
    for name in ('AccountUpdate', 'CategoryUpdate', 'ManagedUpdate', 'TransactionUpdate', 'JournalUpdate', 'MileageUpdate', 'ProtectedMutation'):
        assert 'baseline' in components[name]['required']
    assert 'baselines' in components['ManagedMerge']['required']


def test_missing_posting_identity_returns_safe_field_feedback(client):
    response = client.patch('/api/v1/entities/alpha/journals/journal', headers=HEADERS,
        json={'baseline': TOKEN, 'changes': {'txn_date': '2026-10-05', 'description': '',
            'postings': [{'target_type': 'account', 'target_id': 'cash', 'side': 'Debit', 'amount': '1.00'}]}})
    assert response.status_code == 422
    assert response.json()['error']['fields'] == [
        {'field': 'id', 'code': 'invalid', 'message': 'Check this value.'}]
