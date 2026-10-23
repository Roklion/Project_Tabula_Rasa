import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { captureEvidence, retainEvidence } from './visual-evidence';

const session = {
  actor_id: 'synthetic', organization_id: 'synthetic', entity: { id: 'alpha', name: 'Alpha demonstration' },
  capabilities: ['bookkeeping:read', 'bookkeeping:write', 'bookkeeping:import'], cache_scope: 'foundation-alpha',
  csrf_token: 'synthetic', trusted_development: true,
};
const longName = 'Demonstration operating account with a deliberately long label for responsive bookkeeping';
const account = { id: 'synthetic-account', name: longName, type: 'Bank', classification: 'Asset',
  opening_balance: '1250.00', parent_id: null, active: true, baseline: 'synthetic-baseline' };

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    const json = path.endsWith('/session') ? session : path === '/api/v1/businesses' ? { items: [session.entity] }
      : path.endsWith('/reports/summary') ? {
        profit_loss: { income: '0.00', expenses: '0.00', net: '0.00' },
        balance_sheet: { assets: [], liabilities: [], equity: [], current_earnings: '0.00', total_assets: '0.00',
          total_liabilities: '0.00', total_equity: '0.00', difference: '0.00' }, account_balances: [],
      } : { items: path.endsWith('/accounts') ? [account] : [] };
    return route.fulfill({ json });
  });
});

test.afterEach(async () => { await retainEvidence(test.info()); });

test('light Soft workspace stays light under a dark operating-system preference', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/accounts/new');
  const form = page.locator('.surface.editor');
  await expect(form).toBeVisible();
  await expect(page.locator('html')).toHaveCSS('color-scheme', 'light');
  expect((await form.boundingBox())!.width).toBeLessThanOrEqual(960);
  const name = page.getByLabel('Account name');
  const fine = await page.evaluate(() => matchMedia('(pointer: fine)').matches);
  expect((await name.boundingBox())!.height).toBe(fine ? 40 : 44);
  await expect(name).toHaveCSS('border-radius', '8px');
  await name.focus(); await expect(name).toHaveCSS('outline-style', 'solid');
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze()).violations).toEqual([]);
  await captureEvidence(page, test.info(), 'light-form-dark-system-1440.png');
  await page.goto('/accounts');
  await expect(page.getByRole('rowheader', { name: longName })).toHaveCSS('font-weight', '400');
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze()).violations).toEqual([]);
  await captureEvidence(page, test.info(), 'light-table-dark-system-1440.png');
});

test('representative account form and table reflow with long labels', async ({ page }) => {
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    for (const [surface, route] of [['accounts', '/accounts'], ['create-account', '/accounts/new']] as const) {
      await page.goto(route);
      await expect(page.getByRole('heading', { name: surface === 'accounts' ? 'Accounts' : 'Create account', exact: true })).toBeVisible();
      if (surface === 'create-account') await expect(page.getByLabel('Parent account')).toContainText(longName);
      else {
        const name = page.getByRole('rowheader', { name: longName });
        await expect(name).toBeVisible();
        await expect(name).toHaveCSS('font-weight', '400');
        const region = page.getByRole('region', { name: 'Accounts', exact: true });
        await region.focus();
        await page.keyboard.press('ArrowRight');
        if (width < 760) {
          await expect.poll(() => region.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
          await region.evaluate(element => { element.scrollLeft = 0; });
        }
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
      const accessibility = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
      expect(accessibility.violations).toEqual([]);
      await captureEvidence(page, test.info(), `${surface}-${width}.png`);
    }
  }
});

test('shared global styles leave every existing route family reachable', async ({ page }) => {
  // This sweep loads and captures 48 pages; hosted runners need more than the
  // single-page default budget. Keep each assertion's normal failure timeout.
  test.setTimeout(120_000);
  for (const width of [1440, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    for (const route of ['/', '/reports', '/transactions', '/transactions/new', '/journals/new', '/journals',
      '/categories', '/categories/new', '/payees', '/payees/new', '/payees/merge', '/tags', '/tags/new', '/tags/merge',
      '/assets', '/assets/new', '/mixed-use', '/mixed-use/new', '/recurring', '/recurring/new', '/mileage', '/mileage/new',
      '/transactions/synthetic/receipts', '/data']) {
      await page.goto(route);
      await expect(page.getByRole('main')).toBeVisible();
      await expect(page.getByRole('heading').first()).toBeVisible();
      await expect(page.getByRole('status').filter({ hasText: /Loading/ })).toHaveCount(0);
      await expect(page.getByRole('heading', { name: 'Page unavailable' })).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), route).toBe(true);
      await captureEvidence(page, test.info(), `route-${route.replaceAll('/', '_') || 'dashboard'}-${width}.png`);
    }
  }
});

test('account create keeps keyboard, error, pending and confirmed-success behavior', async ({ page }) => {
  let release: () => void = () => {};
  const pending = new Promise<void>(resolve => { release = resolve; });
  let attempts = 0;
  await page.route('**/api/v1/entities/alpha/accounts', async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    attempts++;
    if (attempts === 1) return route.fulfill({ status: 422, json: { error: { code: 'validation',
      fields: [{ field: 'name', code: 'invalid', message: 'Check this value.' }] }, request_id: 'synthetic-validation' } });
    await pending;
    return route.fulfill({ status: 201, json: account });
  });
  await page.goto('/accounts/new');
  const name = page.getByLabel('Account name');
  await name.fill('Synthetic draft');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(name).toBeFocused();
  await expect(name).toHaveAttribute('aria-invalid', 'true');
  await expect(name).toHaveAccessibleDescription('Check this value.');
  await expect(name).toHaveValue('Synthetic draft');
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('Type', { exact: true })).toBeFocused();
  await expect(page.getByLabel('Type', { exact: true })).toHaveCSS('outline-style', 'solid');
  await page.getByRole('button', { name: 'Back to records' }).click();
  const dialog = page.getByRole('alertdialog', { name: 'Discard draft' });
  await expect(dialog.getByRole('button', { name: 'Keep editing' })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(dialog.getByRole('button', { name: 'Discard draft and close' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Back to records' })).toBeFocused();
  // Explicitly retry after inspecting the rejected draft; there is no automatic retry.
  expect(attempts).toBe(1);
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(name).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Create account', exact: true })).toHaveAttribute('aria-busy', 'true');
  await expect(page.getByRole('button', { name: 'Back to records' })).toBeDisabled();
  release();
  await expect(page.getByRole('status')).toHaveText('Record created.');
  await expect(name).toBeEnabled();
  await expect(name).toHaveValue('');
});

test('disabled action tones stay neutral under the pointer', async ({ page }) => {
  await page.goto('/accounts/new');
  await expect(page.getByRole('heading', { name: 'Create account', exact: true })).toBeVisible();
  // Exercise the shared stylesheet contract with the native markup emitted by
  // ActionButton, including pending (disabled + aria-busy) actions.
  await page.evaluate(() => {
    for (const tone of ['primary', 'secondary', 'destructive']) {
      const button = document.createElement('button');
      button.className = `action-${tone}`;
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      button.textContent = `Pending ${tone}`;
      document.querySelector('main')!.append(button);
    }
  });
  for (const tone of ['primary', 'secondary', 'destructive']) {
    const button = page.getByRole('button', { name: `Pending ${tone}`, exact: true });
    await button.hover();
    await expect(button).toBeDisabled();
    await expect(button).toHaveCSS('background-color', 'rgb(232, 237, 244)');
    await expect(button).toHaveCSS('color', 'rgb(82, 98, 122)');
    await expect(button).toHaveCSS('border-top-color', 'rgb(207, 218, 233)');
  }
});

test('native multiple selectors retain multiline geometry and keyboard selection', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto('/transactions');
  const accounts = page.getByRole('listbox', { name: 'Accounts', exact: true });
  await expect(accounts.getByRole('option')).toHaveCount(1);
  expect((await accounts.boundingBox())!.height).toBeGreaterThan((await page.getByLabel('From', { exact: true }).boundingBox())!.height);
  await accounts.focus();
  await page.keyboard.press('Home');
  await expect(accounts).toHaveValues(['account:synthetic-account']);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
