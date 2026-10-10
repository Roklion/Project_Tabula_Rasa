"""Opt-in #288 browser release gate on retained, synthetic staging only.

No database/admin credentials, remote fault injection, traces or byte deletion.
The same journey is exercised against disposable PostgreSQL in repository CI.
"""

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import uuid4

from .smoke import smoke

ENGINES = ('chromium', 'firefox', 'webkit')
WIDTHS = (1440, 390)


class AlphaError(Exception):
    """Bounded operator guidance; never provider responses or draft values."""


def configuration(environ, release, allow_writes):
    origin = environ.get('TABULA_RASA_PUBLIC_ORIGIN', '')
    parsed = urlsplit(origin)
    if (environ.get('TABULA_RASA_ENVIRONMENT') != 'staging' or not allow_writes
            or parsed.scheme != 'https' or not parsed.hostname
            or parsed.hostname in {'localhost', '127.0.0.1', '::1', 'testserver'}
            or parsed.netloc != parsed.hostname or parsed.path or parsed.query or parsed.fragment
            or not re.fullmatch('[0-9a-f]{40}', release)
            or not environ.get('TABULA_RASA_ALPHA_USERNAME') or not environ.get('TABULA_RASA_ALPHA_PASSWORD')):
        raise AlphaError('Select canonical HTTPS staging, an exact release and explicit synthetic-write consent.')
    return origin, environ['TABULA_RASA_ALPHA_USERNAME'], environ['TABULA_RASA_ALPHA_PASSWORD']


def checked(response, status=200):
    if response.status != status:
        raise AlphaError('A required alpha operation failed. Inspect staging using the run marker; do not retry blindly.')
    return response


def rejected(response, status, code):
    if checked(response, status).json().get('error', {}).get('code') != code:
        raise AlphaError('The protected mutation returned the wrong failure contract.')


def preflight(context, expected_entity, origin):
    session = checked(context.request.get('/api/v1/session')).json()
    if (session.get('entity', {}).get('id') != expected_entity or not session.get('trusted_development')
            or not {'bookkeeping:read', 'bookkeeping:write'}.issubset(session.get('capabilities', []))):
        raise AlphaError('The gate requires the fixed, writable synthetic context.')
    prefix = '/api/v1/entities/' + expected_entity + '/'
    if context.request.get(prefix + 'documents').status != 200:
        raise AlphaError('Essential receipt storage is unavailable. Bind the authorized staging DocumentStore before acceptance.')
    return prefix, {'Origin': origin, 'X-CSRF-Token': session['csrf_token']}


def create_reference(page, resource, name, *, kind=None):
    page.goto('/' + resource + '/new')
    page.get_by_label('Account name' if resource == 'accounts' else 'Category name' if resource == 'categories' else 'Name', exact=True).fill(name)
    if kind:
        page.get_by_label('Kind', exact=True).select_option(kind)
    noun = 'category' if resource == 'categories' else resource[:-1]
    with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/' + resource)) as created:
        page.get_by_role('button', name='Create ' + noun, exact=True).click()
    row = checked(created.value, 201).json()
    return row['id']


def create_transaction(page, marker, kind, amount, account, category='', *, destination='', payee='', tag=''):
    page.goto('/transactions/new')
    page.get_by_label('Type', exact=True).select_option(kind)
    page.get_by_label('Date', exact=True).fill('2026-10-01')
    page.get_by_label('Amount', exact=True).fill(amount)
    page.get_by_label('To account' if kind == 'Income' else 'From account', exact=True).select_option(account)
    if kind == 'Transfer':
        page.get_by_label('To account', exact=True).select_option(destination)
    else:
        page.get_by_label('Category', exact=True).select_option(category)
    if payee:
        page.get_by_label('Payee / customer', exact=True).select_option(payee)
    if tag:
        page.get_by_label('Tags', exact=True).select_option(tag)
    page.get_by_label('Description / memo', exact=True).fill(marker + ' ' + kind)
    with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/transactions')) as saved:
        page.get_by_role('button', name='Save transaction', exact=True).click()
    return checked(saved.value, 201).json()


def open_transaction(page, row):
    page.goto('/transactions')
    page.get_by_role('button', name=f"Edit {row['txn_date']} · {row['description']} · {row['amount']}", exact=True).click()
    from playwright.sync_api import expect
    expect(page.get_by_label('Description / memo', exact=True)).to_have_value(row['description'])


def journey(context, peer, *, origin, entity, marker):
    """Supported core path; accounting/validation remain owned by services."""
    from playwright.sync_api import expect

    prefix, headers = preflight(context, entity, origin)
    before = checked(context.request.get(prefix + 'reports/summary')).json()
    page, other = context.new_page(), peer.new_page()
    account = create_reference(page, 'accounts', marker + ' Bank')
    destination = create_reference(page, 'accounts', marker + ' Destination')
    expense_category = create_reference(page, 'categories', marker + ' Expense')
    income_category = create_reference(page, 'categories', marker + ' Income', kind='Income')
    payee = create_reference(page, 'payees', marker + ' Vendor')
    tag = create_reference(page, 'tags', marker + ' Tag')
    expense = create_transaction(page, marker, 'Expense', '10.25', account, expense_category, payee=payee, tag=tag)
    open_transaction(page, expense)
    open_transaction(other, expense)
    page.get_by_label('Amount', exact=True).fill('11.25')
    with page.expect_response(lambda response: response.request.method == 'PATCH') as saved:
        page.get_by_role('button', name='Save changes', exact=True).click()
    current = checked(saved.value).json()
    other.get_by_label('Description / memo', exact=True).fill(marker + ' stale draft')
    with other.expect_response(lambda response: response.request.method == 'PATCH') as stale:
        other.get_by_role('button', name='Save changes', exact=True).click()
    rejected(stale.value, 409, 'stale')
    expect(other.get_by_role('alert')).to_contain_text('Your draft is preserved')
    expect(other.get_by_label('Description / memo', exact=True)).to_have_value(marker + ' stale draft')
    other.get_by_role('button', name='Delete', exact=True).click()
    with other.expect_response(lambda response: response.request.method == 'DELETE') as stale_delete:
        other.get_by_role('button', name='Confirm delete', exact=True).click()
    rejected(stale_delete.value, 409, 'stale')
    path = prefix + 'transactions/' + expense['id']
    rejected(context.request.patch(path, headers=headers, data={'changes': saved.value.request.post_data_json['changes']}), 422, 'baseline_required')
    rejected(context.request.delete(path, headers=headers, data={}), 422, 'baseline_required')
    other.get_by_role('button', name='Review latest record', exact=True).click()
    other.get_by_role('button', name='Discard draft and reload', exact=True).click()
    expect(other.get_by_label('Amount', exact=True)).to_have_value('11.25')
    expect(other.get_by_label('Description / memo', exact=True)).to_have_value(current['description'])

    # Required provider availability is checked before the first create above.
    page.goto('/transactions/' + expense['id'] + '/receipts')
    content = b'%PDF-1.4\n% Tabula Rasa synthetic technical-alpha receipt\n%%EOF\n'
    page.get_by_label('Receipt files').set_input_files({'name': marker + '.pdf', 'mimeType': 'application/pdf', 'buffer': content})
    page.get_by_role('button', name='Attach selected receipts', exact=True).click()
    expect(page.get_by_role('status').filter(has_text='1 receipt attached.')).to_be_visible()
    with page.expect_download() as download:
        page.get_by_role('link', name='Download ' + marker + '.pdf', exact=True).click()
    if Path(download.value.path()).read_bytes() != content:
        raise AlphaError('Receipt byte verification failed.')
    page.get_by_role('button', name='Remove ' + marker + '.pdf', exact=True).click()
    page.get_by_role('button', name='Confirm remove', exact=True).click()
    expect(page.get_by_role('status').filter(has_text='Receipt reference removed. File retained.')).to_be_visible()
    page.get_by_role('button', name='Link ' + marker + '.pdf', exact=True).click()
    expect(page.get_by_role('status').filter(has_text='Receipt linked.')).to_be_visible()
    page.get_by_role('button', name='Remove ' + marker + '.pdf', exact=True).click()
    page.get_by_role('button', name='Confirm remove', exact=True).click()
    expect(page.get_by_role('button', name='Link ' + marker + '.pdf', exact=True)).to_be_visible()

    income = create_transaction(page, marker, 'Income', '30.00', account, income_category)
    transfer = create_transaction(page, marker, 'Transfer', '3.00', account, destination=destination)
    page.goto('/journals/new')
    page.get_by_label('Date', exact=True).fill('2026-10-01')
    page.get_by_label('Description / memo', exact=True).fill(marker + ' Journal')
    page.get_by_label('Account or category', exact=True).nth(0).select_option('category')
    page.get_by_label('Target', exact=True).nth(0).select_option(expense_category)
    page.get_by_label('Target', exact=True).nth(1).select_option(account)
    page.get_by_label('Amount', exact=True).nth(0).fill('2.00')
    page.get_by_label('Amount', exact=True).nth(1).fill('1.00')
    expect(page.get_by_role('button', name='Save journal', exact=True)).to_be_disabled()
    page.get_by_label('Amount', exact=True).nth(1).fill('2.00')
    with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/journals')) as journal:
        page.get_by_role('button', name='Save journal', exact=True).click()
    checked(journal.value, 201)
    page.get_by_role('button', name='Back to records', exact=True).click()
    page.get_by_role('button', name='Edit 2026-10-01 · ' + marker + ' Journal', exact=True).click()
    page.get_by_label('Description / memo', exact=True).fill(marker + ' Reviewed journal')
    page.get_by_role('button', name='Save changes', exact=True).click()
    expect(page.get_by_role('status').filter(has_text='Changes saved.')).to_be_visible()
    page.goto('/transactions')
    page.get_by_label('Search transactions', exact=True).fill(marker)
    expect(page.get_by_role('status').filter(has_text='4 matching entries')).to_be_visible()
    expect(page.get_by_role('rowheader', name='↳ Posting', exact=True)).to_have_count(2)
    if page.evaluate('document.documentElement.scrollWidth > window.innerWidth'):
        raise AlphaError('Core ledger overflows the viewport.')
    page.goto('/reports')
    expect(page.get_by_role('heading', name='Balance sheet', exact=True)).to_be_visible()
    after = checked(context.request.get(prefix + 'reports/summary')).json()
    for field, delta in (('income', '30.00'), ('expenses', '13.25'), ('net', '16.75')):
        if Decimal(after['profit_loss'][field]) - Decimal(before['profit_loss'][field]) != Decimal(delta):
            raise AlphaError('Core report accounting verification failed; inspect the synthetic run.')
    metrics = page.locator('dl.metrics').first.get_by_role('definition')
    for index, field in enumerate(('income', 'expenses', 'net')):
        expect(metrics.nth(index)).to_have_text(after['profit_loss'][field])
    if after['balance_sheet']['difference'] != '0.00':
        raise AlphaError('The accounting equation failed.')
    expect(page.get_by_role('status').filter(has_text='Assets = Liabilities + Equity.')).to_be_visible()

    # Only this run's known records are removed through freshly loaded forms.
    # A failed/uncertain operation stops; no broad cleanup or byte rollback.
    for row in (current, income, transfer):
        open_transaction(page, row)
        page.get_by_role('button', name='Delete', exact=True).click()
        page.get_by_role('button', name='Confirm delete', exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Record deleted.')).to_be_visible()
    page.goto('/journals')
    page.get_by_role('button', name='Edit 2026-10-01 · ' + marker + ' Reviewed journal', exact=True).click()
    page.get_by_role('button', name='Delete', exact=True).click()
    page.get_by_role('button', name='Confirm delete', exact=True).click()
    expect(page.get_by_role('status').filter(has_text='Record deleted.')).to_be_visible()
    page.close()
    other.close()


def run(environ, release, *, allow_writes=False):
    origin, username, password = configuration(environ, release, allow_writes)
    # Reuse #279's anonymous restriction, identity, routing and DB read smoke.
    smoke(origin, username, password, release)
    from playwright.sync_api import sync_playwright
    run_id = uuid4().hex
    print(json.dumps({'run': run_id, 'release': release, 'status': 'started'}), flush=True)
    with sync_playwright() as playwright:
        for engine in ENGINES:
            browser = getattr(playwright, engine).launch()
            try:
                for width in WIDTHS:
                    options = dict(base_url=origin, http_credentials={'username': username, 'password': password},
                                   viewport={'width': width, 'height': 1000 if width == 1440 else 844})
                    with browser.new_context(**options) as context, browser.new_context(**options) as peer:
                        journey(context, peer, origin=origin, entity='alpha-synthetic', marker=f'Alpha-{run_id}-{engine}-{width}')
                    print(json.dumps({'run': run_id, 'engine': engine, 'width': width, 'status': 'passed'}), flush=True)
            finally:
                browser.close()
    # A changed release during a local/manual invocation cannot pass the gate.
    smoke(origin, username, password, release)
    return {'run': run_id, 'release': release, 'status': 'alpha_browser_passed'}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--release', required=True)
    parser.add_argument('--allow-synthetic-writes', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = run(dict(os.environ), args.release, allow_writes=args.allow_synthetic_writes)
    except Exception as error:
        message = str(error) if isinstance(error, AlphaError) else 'Alpha browser gate failed. Inspect the synthetic run in staging.'
        raise SystemExit(message) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
