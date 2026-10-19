import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { coreResponse, session as coreSession, longName } from './core-fixture';
import { secondaryResponse } from './secondary-fixture';
import { captureEvidence, retainEvidence } from './visual-evidence';

const session = { ...coreSession, trusted_development: false, entity: { id: 'alpha', name: longName },
  capabilities: [...coreSession.capabilities, 'members:manage', 'ownership:manage', 'entity:manage'] };
const member = { user_id: 'synthetic-member', display_name: 'Synthetic collaborator', role: 'read_only', state: 'active', authorization_version: 1 };

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = path.endsWith('/session') ? session : path === '/api/v1/entities' ? { items: [session.entity, { id: 'beta', name: longName + ' second business' }] }
      : path.endsWith('/members') ? { items: [member] } : path.endsWith('/invitations') ? { items: [] }
        : path.includes('/mileage') ? secondaryResponse(url) : coreResponse(url);
    return route.fulfill({ json });
  });
});
test.afterEach(async () => { await retainEvidence(test.info()); });

test('shared shell and section rhythm with long business labels at three widths', async ({ page }) => {
  test.setTimeout(90_000);
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const path of ['/workspace', '/', '/transactions', '/mileage']) {
      await page.goto(path);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      await expect(page.getByRole('status').filter({ hasText: /Loading|Checking/ })).toHaveCount(0);
      if (!process.env.TABULA_RASA_UI_401_BEFORE) {
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
        const selector = page.getByLabel('Select business', { exact: true });
        await expect(selector).toHaveValue('alpha');
        await selector.focus(); await expect(selector).toBeFocused();
        await expect(selector).toHaveCSS('outline-style', 'solid');
        const selectorFits = await selector.evaluate(element => element.getBoundingClientRect().right <= element.parentElement!.getBoundingClientRect().right);
        expect(selectorFits).toBe(true);
        if (path === '/workspace') {
          await expect(page.locator('header').first()).toContainText('Workspace & members');
          const review = await page.getByRole('button', { name: 'Review membership change' }).boundingBox();
          const grant = await page.getByRole('button', { name: 'Grant ownership', exact: true }).boundingBox();
          if (review && grant && grant.y >= review.y + review.height) expect(grant.y - review.y - review.height).toBeGreaterThanOrEqual(8);
          const invitationsEnd = await page.getByText('No invitations.', { exact: true }).boundingBox();
          const addHeading = await page.getByRole('heading', { name: 'Add a business', exact: true }).boundingBox();
          expect(addHeading!.y - invitationsEnd!.y - invitationsEnd!.height).toBeGreaterThanOrEqual(24);
          const setupAction = await page.getByRole('button', { name: 'Review defaults', exact: true }).boundingBox();
          const respond = await page.getByRole('heading', { name: 'Respond to an invitation', exact: true }).boundingBox();
          expect(respond!.y - setupAction!.y - setupAction!.height).toBeGreaterThanOrEqual(32);
        }
        if (path === '/') {
          const actions = await page.getByRole('region', { name: 'Ledger next actions' }).boundingBox();
          const period = await page.getByRole('region', { name: 'Report period' }).boundingBox();
          expect(period!.y - actions!.y - actions!.height).toBeGreaterThanOrEqual(24);
        }
        expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([]);
      }
      await captureEvidence(page, test.info(), `${path.slice(1) || 'dashboard'}-${width}.png`);
    }
  }
});

test('table filters retain active values, results and scoped collapse preferences', async ({ page }) => {
  await page.goto('/transactions');
  await page.getByLabel('Type', { exact: true }).selectOption('Journal');
  await expect(page.getByText('1 matching entries', { exact: true })).toBeVisible();
  const toggle = page.getByRole('button', { name: /Filter ledger/ });
  await toggle.focus(); await page.keyboard.press('Enter');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByLabel('Type', { exact: true })).toBeHidden();
  await expect(page.getByText('Journal', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('1 matching entries', { exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Ledger', exact: true })).toContainText('Complete synthetic journal');
  await captureEvidence(page, test.info(), 'ledger-collapsed-active.png');
  await toggle.press('Space');
  await expect(page.getByLabel('Type', { exact: true })).toHaveValue('Journal');
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
  await expect(page.getByText('3 matching entries', { exact: true })).toBeVisible();
  await toggle.click();
  await page.getByRole('link', { name: 'Mileage', exact: true }).click();
  await expect(page.getByRole('button', { name: /Hide filters/ })).toBeVisible();
  await page.getByLabel('From', { exact: true }).fill('2026-10-08');
  await expect(page.getByText('Trips: 0', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: /Hide filters/ }).click();
  await expect(page.getByText('From 2026-10-08', { exact: true })).toBeVisible();
  await expect(page.getByText('Trips: 0', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: /Show filters/ }).click();
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
  await expect(page.getByText('Trips: 1', { exact: false })).toBeVisible();
  await page.getByRole('link', { name: 'Transactions', exact: true }).first().click();
  await expect(page.getByRole('button', { name: /Show filters/ })).toHaveAttribute('aria-expanded', 'false');
  // Navigation resets filter values as before; only the presentation preference persists.
  await expect(page.getByText('All entries · Date / Descending', { exact: true })).toBeVisible();
});

for (const outcome of ['success', 'reauthentication_required', 'uncertain'] as const) {
  test(`membership delayed ${outcome} keeps feedback and blocks duplicate mutation`, async ({ page }) => {
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    let calls = 0;
    await page.route('**/members/synthetic-member', async route => {
      calls++; await gate;
      if (outcome === 'success') await route.fulfill({ status: 204 });
      else if (outcome === 'uncertain') await route.abort('failed');
      else await route.fulfill({ status: 403, json: { error: { code: outcome, message: 'Safe synthetic denial', fields: [] }, request_id: 'synthetic-request' } });
    });
    await page.goto('/workspace');
    await page.getByRole('button', { name: 'Review membership change' }).click();
    const confirm = page.getByRole('button', { name: 'Confirm membership change' });
    await confirm.click();
    await expect(confirm).toBeDisabled();
    await expect(page.getByRole('status').filter({ hasText: 'Working' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('alertdialog')).toBeVisible();
    await captureEvidence(page, test.info(), `membership-${outcome}-pending.png`);
    expect(calls).toBe(1); release();
    if (outcome === 'success') await expect(page.getByText('Membership change confirmed.', { exact: true })).toBeVisible();
    else {
      await expect(page.getByRole('button', { name: 'Keep current membership' })).toBeEnabled();
      if (outcome === 'uncertain') {
        await expect(page.getByText(/The outcome could not be confirmed/)).toBeVisible();
        await expect(confirm).toBeDisabled();
      } else {
        const login = page.getByRole('link', { name: 'Sign in again' });
        await expect(login).toBeVisible();
        await confirm.focus(); await page.keyboard.press('Tab');
        await expect(login).toBeFocused();
        await page.keyboard.press('Shift+Tab'); await expect(confirm).toBeFocused();
        await page.getByRole('button', { name: 'Keep current membership' }).focus();
        await page.keyboard.press('Shift+Tab'); await expect(login).toBeFocused();
      }
    }
    expect(calls).toBe(1);
  });
}
