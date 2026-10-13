import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { execFileSync } from 'node:child_process';
import { readdir, writeFile } from 'node:fs/promises';

const baselineCapture = process.env.TABULA_RASA_VISUAL_BASELINE === '1';
const longName = 'Synthetic business label with deliberately long words for responsive fields and management records';
const longId = 'synthetic-record-identity-with-long-stable-provenance-0123456789';
const session = { actor_id: 'synthetic', organization_id: 'synthetic', entity: { id: 'alpha', name: 'Alpha demonstration' },
  capabilities: ['bookkeeping:read', 'bookkeeping:write'], cache_scope: 'forms-secondary-alpha', csrf_token: 'synthetic', trusted_development: true };
const account = { id: 'account', name: longName, type: 'Bank', classification: 'Asset', opening_balance: '0.00', parent_id: null, active: true, baseline: 'loaded-account' };
const accumulated = { ...account, id: 'accumulated', name: 'Accumulated depreciation', type: 'Other' };
const category = { id: 'category', name: 'Synthetic expense category with a long descriptive label', kind: 'Expense', parent_id: null, baseline: 'loaded-category' };
const references = [{ id: 'reference', name: longName, active: true, baseline: 'loaded-reference' },
  { id: 'source', name: 'Second synthetic source with another long descriptive name', active: true, baseline: 'loaded-source' }];
const transaction = { id: 'transaction', txn_date: '2026-10-07', kind: 'Expense', amount: '1234.56', account_id: 'account', to_account_id: '',
  category_id: 'category', payee_id: 'reference', tag_ids: ['reference'], description: longName, reference: 'Synthetic reference',
  source_type: '', baseline: 'loaded-transaction' };
const mixed = { ...transaction, id: 'mixed', total_expense: '1234.56', business_use_percentage: '60', allocated_amount: '740.74',
  allocation_rationale: 'Synthetic allocation rationale spanning several words and lines in a narrow viewport.', linked_transaction_id: longId,
  ledger_status: 'linked', recurring_schedule_id: '', recurring_scheduled_date: '', recurring_occurrence_type: '', baseline: 'loaded-mixed' };
const recurring = { ...transaction, id: 'recurring', name: longName, source_kind: 'transaction', start_date: '2026-10-01', end_date: '',
  recurrence_unit: 'month', recurrence_interval: '1', total_expense: '', business_use_percentage: '100', allocation_rationale: '', status: 'active',
  next_due_date: '2026-11-01', latest_current_occurrence_date: '2026-10-01', attention_message: '', baseline: 'loaded-recurring' };
const asset = { id: 'asset', name: longName, asset_type: 'Equipment', notes: 'Synthetic multiline notes.\nA second line preserves useful context.',
  acquisition_date: '2026-01-01', depreciation_start_date: '2026-01-01', cost_basis: '12345.67', salvage_value: '0.00', useful_life_quarters: '4',
  depreciation_expense_account_id: 'category', accumulated_depreciation_account_id: 'accumulated', payee_id: 'reference', tag_ids: ['reference'],
  reference: 'Synthetic reference', source_transaction_id: longId, status: 'active', retired_date: '', depreciation_method: 'straight_line', baseline: 'loaded-asset' };
const assetDetail = { asset, terms_locked: true, posting_accounts_locked: true, can_delete: false,
  schedule: [{ sequence: 1, scheduled_date: '2026-03-31', depreciation_amount: '3086.42', cumulative_depreciation: '3086.42', remaining_book_value: '9259.25',
    override_reason: 'Synthetic override reason with enough words to wrap.', posting_status: 'Posted', journal_entry_id: longId }], history: [{ id: 'posted' }] };
const mileage = { id: 'mileage', trip_date: '2026-10-07', miles: '123.4', vehicle: 'Synthetic vehicle', start_location: longName,
  destination: 'Synthetic destination with a long address and business name', business_purpose: 'Visit the synthetic demonstration business for a scheduled appointment.',
  notes: 'Synthetic trip notes.\nSecond line for a narrow screen.', tag_ids: ['reference'], baseline: 'loaded-mileage' };
const receipt = { id: longId, filename: 'synthetic-receipt-with-a-deliberately-long-filename-for-narrow-screens-0123456789.pdf', mime_type: 'application/pdf', byte_size: 1234, sha256: 'a'.repeat(64) };

async function transport(page: Page, capabilities = session.capabilities) {
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    // Every request stays intercepted. Unmatched reads are empty synthetic lists;
    // mutation tests below replace only the endpoint they explicitly exercise.
    const json = path.endsWith('/session') ? { ...session, capabilities } : path === '/api/v1/entities' ? { items: [session.entity] }
      : path.endsWith('/accounts') ? { items: [account, accumulated] } : path.endsWith('/categories') ? { items: [category] }
        : path.endsWith('/payees') || path.endsWith('/tags') ? { items: references } : path.endsWith('/transactions') ? { items: [transaction] }
          : path.endsWith('/mixed-use/allocation') ? { allocated_amount: '740.74' } : path.endsWith('/mixed-use/mixed') ? mixed : path.endsWith('/mixed-use') ? { items: [mixed] }
            : path.endsWith('/recurring/recurring') ? { schedule: recurring, occurrences: [{ ...transaction, id: longId, recurring_occurrence_type: 'initial', recurring_scheduled_date: '2026-10-01', source_id: '' }] }
              : path.endsWith('/recurring') ? { items: [recurring] } : path.endsWith('/assets/types') ? { items: ['Equipment'] }
                : path.endsWith('/assets/asset') ? assetDetail : path.endsWith('/assets') ? { items: [asset] }
                  : path.endsWith('/mileage/mileage') ? mileage : path.endsWith('/mileage') ? { items: [mileage] }
                    : path.endsWith('/receipts') ? { items: [receipt] } : path.endsWith('/documents') ? { items: [{ ...receipt, id: 'unreferenced', filename: 'synthetic-unreferenced.pdf' }], needing_integrity: 0 }
                      : { items: [] };
    return route.fulfill({ json });
  });
}

async function capture(page: Page, name: string, accessibility = true) {
  const width = page.viewportSize()!.width;
  const contained = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
  if (!baselineCapture) {
    if (!contained) {
      // Keep bounds/style evidence for engine-specific regressions. Wide table
      // descendants are expected only when their named region contains them.
      const bounds = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth, documentWidth: document.documentElement.scrollWidth,
        elements: Array.from(document.querySelectorAll<HTMLElement>('body *')).filter(element => {
          const rect = element.getBoundingClientRect();
          return rect.right > document.documentElement.clientWidth || element.scrollWidth > element.clientWidth;
        }).map(element => {
          const rect = element.getBoundingClientRect(); const style = getComputedStyle(element);
          return { tag: element.tagName, id: element.id, className: element.className, parent: element.parentElement?.className,
            left: rect.left, right: rect.right, width: rect.width, scrollWidth: element.scrollWidth, clientWidth: element.clientWidth,
            minWidth: style.minWidth, maxWidth: style.maxWidth, overflowX: style.overflowX, display: style.display,
            gridTemplateColumns: style.gridTemplateColumns, whiteSpace: style.whiteSpace, overflowWrap: style.overflowWrap,
            insideTableRegion: Boolean(element.closest('.tableScroll')) };
        }) }));
      await writeFile(test.info().outputPath(`${name}-${width}-overflow.json`), JSON.stringify(bounds, null, 2));
    }
    expect(contained, name + ' must contain horizontal overflow in named table regions').toBe(true);
    if (accessibility) {
      const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
      expect(results.violations, name).toEqual([]);
    }
  }
  await page.screenshot({ path: test.info().outputPath(`${name}-${width}.png`), fullPage: true });
}

test.beforeEach(async ({ page }) => { await transport(page); });
test.afterEach(async ({ page }) => {
  const screenshots = (await readdir(test.info().outputPath('.'))).filter(name => name.endsWith('.png'));
  await writeFile(test.info().outputPath('revision.json'), JSON.stringify({
    revision: process.env.TABULA_RASA_VISUAL_REVISION ?? execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
    worktreeChanges: baselineCapture ? 'Untouched HEAD archive; test harness only.' : execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim(),
    baselineCapture, project: test.info().project.name, finalViewport: page.viewportSize(),
    screenshots: screenshots.map(filename => { const width = Number(filename.match(/-(1440|390|320)\.png$/)?.[1]);
      return { filename, viewport: { width, height: width === 1440 ? 1000 : 844 } }; }),
    data: 'Synthetic intercepted transport only; no live service, ledger, credentials or receipt contents.',
  }, null, 2));
});

test('identity availability surfaces share controls without exposing private routes', async ({ page }) => {
  test.skip(baselineCapture, 'Identity sessions were delivered after the original visual baseline.');
  test.setTimeout(90_000);
  let state: 'signed-out' | 'unavailable' | 'needs-setup' = 'signed-out';
  await page.route('**/api/v1/session', route => state === 'needs-setup'
    ? route.fulfill({ json: { ...session, trusted_development: false, state: 'needs_setup', entity: null, capabilities: [] } })
    : route.fulfill({ status: state === 'signed-out' ? 401 : 503, json: { error: { code: state === 'signed-out' ? 'unauthorized' : 'unavailable' } } }));
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    for (const mode of ['signed-out', 'unavailable', 'needs-setup'] as const) {
      state = mode;
      await page.goto('/accounts');
      await expect(page.getByRole('heading', { name: mode === 'needs-setup' ? 'Workspace setup required' : 'Project Tabula Rasa', exact: true })).toBeVisible();
      await expect(page.getByRole('navigation', { name: 'Main navigation' })).toHaveCount(0);
      await expect(page.getByRole('region', { name: 'Accounts', exact: true })).toHaveCount(0);
      if (mode === 'signed-out') await expect(page.getByRole('link', { name: 'Sign in', exact: true })).toHaveAttribute('href', '/api/v1/auth/login');
      else await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible();
      if (mode === 'unavailable') await expect(page.getByRole('alert')).toContainText('The requested data could not be loaded.');
      await capture(page, 'identity-' + mode);
    }
  }
});

test('core form visual evidence at desktop and both narrow widths', async ({ page }) => {
  test.setTimeout(180_000);
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    for (const [name, path, heading] of [['transaction-create', '/transactions/new', 'Save transaction'], ['journal-create', '/journals/new', 'Save journal'], ['merge-payees', '/payees/merge', 'Merge payees']] as const) {
      await page.goto(path);
      await expect(page.getByRole('heading', { name: heading, exact: true }).first()).toBeVisible();
      await expect(page.getByRole('status').filter({ hasText: /Loading/ })).toHaveCount(0);
      if (name === 'merge-payees') await page.getByRole('button', { name: 'Merge payees', exact: true }).click();
      if (!baselineCapture && name !== 'merge-payees') {
        const memo = page.getByRole('textbox', { name: 'Description / memo', exact: true });
        await expect(memo).toHaveCSS('min-height', '112px');
        await expect(memo).toHaveCSS('resize', 'vertical');
        expect((await memo.boundingBox())!.height).toBeGreaterThanOrEqual(112);
        if (name === 'transaction-create') {
          const tags = page.getByRole('listbox', { name: 'Tags', exact: true });
          await expect(tags).toHaveCSS('min-height', '128px');
          expect((await tags.boundingBox())!.height).toBeGreaterThanOrEqual(128);
        }
      }
      await capture(page, name);
    }
  }
});

test('populated secondary visual evidence preserves provenance and readable recovery surfaces', async ({ page }) => {
  test.setTimeout(180_000);
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    for (const [name, path, heading] of [['asset-detail', '/assets/asset', 'Asset detail'], ['mixed-use-detail', '/mixed-use/mixed', 'Mixed-use expense'],
      ['recurring-detail', '/recurring/recurring', 'Recurring schedule'], ['mileage-list', '/mileage', 'Mileage'], ['mileage-create', '/mileage/new', 'Add trip'],
      ['receipt-management', '/transactions/transaction/receipts', 'Receipts']] as const) {
      await page.goto(path);
      await expect(page.getByRole('heading', { name: heading, exact: true }).first()).toBeVisible();
      await expect(page.getByRole('status').filter({ hasText: /Loading/ })).toHaveCount(0);
      if (name === 'receipt-management') await page.getByText('Inspect ' + receipt.filename, { exact: true }).click();
      if (name === 'asset-detail') {
        await expect(page.getByLabel('Cost basis')).toBeDisabled();
        await expect(page.getByRole('region', { name: 'Depreciation schedule', exact: true }).getByText(longId)).toBeVisible();
      }
      if (name === 'mileage-list' && !baselineCapture) {
        const region = page.getByRole('region', { name: 'Mileage log', exact: true });
        await region.focus(); await page.keyboard.press('ArrowRight');
        await expect.poll(() => region.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
        await region.evaluate(element => { element.scrollLeft = 0; });
        await expect(region.getByRole('columnheader', { name: 'Miles', exact: true })).toHaveCSS('text-align', 'right');
      }
      await capture(page, name);
    }
  }
});

test('protected conflicts retain draft and loaded token through keyboard review and explicit reload', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  const submitted: { baseline: string; changes: { name: string } }[] = [];
  let latest = false;
  await page.route(/\/api\/v1\/entities\/alpha\/categories(?:\/[^/]+)?$/, async route => {
    if (route.request().method() === 'PATCH') {
      submitted.push(route.request().postDataJSON());
      return route.fulfill({ status: 409, json: { error: { code: 'stale' }, request_id: 'synthetic-conflict-reference-with-long-description-0123456789' } });
    }
    return route.fulfill({ json: { items: [{ ...category, name: latest ? 'Latest saved category' : category.name, baseline: latest ? 'latest-category' : category.baseline }] } });
  });
  await page.goto('/categories');
  await page.getByRole('button', { name: 'Edit ' + category.name, exact: true }).click();
  const name = page.getByLabel('Category name');
  await name.fill('Preserved synthetic draft');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Your draft is preserved');
  expect(submitted).toEqual([{ baseline: category.baseline, changes: { name: 'Preserved synthetic draft', kind: 'Expense', parent_id: '' } }]);
  const review = page.getByRole('button', { name: 'Review latest record', exact: true });
  await review.focus(); await page.keyboard.press('Enter');
  const dialog = page.getByRole('alertdialog', { name: 'Reload record', exact: true });
  await expect(dialog.getByRole('button', { name: 'Keep draft', exact: true })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(dialog.getByRole('button', { name: 'Discard draft and reload', exact: true })).toBeFocused();
  await page.keyboard.press('Escape'); await expect(review).toBeFocused();
  await expect(name).toHaveValue('Preserved synthetic draft');
  expect(submitted).toHaveLength(1);
  await capture(page, 'protected-conflict');
  latest = true;
  await review.click(); await dialog.getByRole('button', { name: 'Discard draft and reload', exact: true }).click();
  await expect(name).toHaveValue('Latest saved category');
  await name.fill('New explicit draft'); await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  expect(submitted[1].baseline).toBe('latest-category');
});

test('transaction validation associates multiline errors and journal rows keep keyboard operations', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/api/v1/entities/alpha/transactions', route => route.request().method() === 'POST'
    ? route.fulfill({ status: 422, json: { error: { code: 'validation', fields: [{ field: 'description', code: 'invalid' }, { field: 'reference', code: 'invalid' }] }, request_id: 'synthetic-validation' } })
    : route.fallback());
  await page.goto('/transactions/new');
  await page.getByLabel('From account', { exact: true }).selectOption('account');
  await page.getByLabel('Category', { exact: true }).selectOption('category');
  await page.getByLabel('Amount', { exact: true }).fill('12.34');
  await page.getByLabel('Description / memo').fill('Synthetic first line\nSynthetic second line retained during validation.');
  await page.getByRole('button', { name: 'Save transaction', exact: true }).click();
  const description = page.getByLabel('Description / memo');
  await expect(description).toHaveAttribute('aria-invalid', 'true');
  await expect(description).toHaveAccessibleDescription('Check this value.');
  await expect(description).toBeFocused();
  await expect(description).toHaveValue('Synthetic first line\nSynthetic second line retained during validation.');
  await expect(description).toHaveCSS('border-top-color', 'rgb(179, 58, 58)');
  const reference = page.getByLabel('Reference', { exact: true });
  await expect(reference).toHaveAttribute('aria-invalid', 'true');
  await expect(reference).toHaveCSS('border-top-color', 'rgb(179, 58, 58)');
  await capture(page, 'transaction-validation');
  await page.goto('/journals/new');
  await page.getByRole('button', { name: 'Add posting', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Posting 3', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Remove posting 3', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Posting 3', exact: true })).toHaveCount(0);
  await expect(page.getByRole('status')).toContainText('Difference: 0.00');
  await capture(page, 'journal-keyboard');
});

test('read-only secondary details and unconfigured receipts expose truthful availability', async ({ page }) => {
  await page.unroute('**/api/v1/**'); await transport(page, ['bookkeeping:read']);
  await page.setViewportSize({ width: 320, height: 844 });
  for (const [path, title] of [['/assets/asset', 'Saved asset terms'], ['/mixed-use/mixed', 'Saved mixed-use expense'], ['/recurring/recurring', 'Saved recurring schedule']] as const) {
    await page.goto(path);
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /Save changes|Delete|Post due|Pause schedule|End schedule/ })).toHaveCount(0);
    await capture(page, title.toLowerCase().replaceAll(' ', '-'));
  }
  await page.route('**/api/v1/entities/alpha/transactions/transaction/receipts', route => route.fulfill({ status: 503, json: { error: { code: 'document_storage_unavailable' } } }));
  await page.goto('/transactions/transaction/receipts');
  await expect(page.getByText('Receipt storage must be configured for this business before receipts are available.')).toBeVisible();
  await expect(page.getByLabel('Receipt files', { exact: true })).toHaveCount(0);
  await capture(page, 'receipts-unavailable');
});
