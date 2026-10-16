import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { secondaryResponse } from './secondary-fixture';
import { captureEvidence, retainEvidence } from './visual-evidence';

// A local widget exercises the host layout; no Google script or provider calls.
const placesStub = () => {
  class PreviewPlace extends HTMLElement {
    value = '';
    connectedCallback() {
      const input = document.createElement('input');
      input.setAttribute('aria-label', this.getAttribute('aria-label')!);
      input.addEventListener('input', () => { this.value = input.value; this.dispatchEvent(new Event('input')); });
      const choose = document.createElement('button'); choose.type = 'button';
      choose.textContent = 'Choose ' + this.getAttribute('aria-label');
      choose.onclick = () => this.dispatchEvent(Object.assign(new Event('gmp-select'), {
        placePrediction: { toPlace: () => ({ id: input.value, fetchFields: async () => {} }) },
      }));
      this.append(input, choose);
    }
  }
  customElements.define('preview-place', PreviewPlace);
  Object.assign(window, { google: { maps: { importLibrary: async () => ({ PlaceAutocompleteElement: PreviewPlace }) } } });
};

test.afterEach(async () => { await retainEvidence(test.info()); });

test('merged exports mixed-use receipts and configured Maps share the accepted presentation', async ({ page }) => {
  test.setTimeout(120_000);
  let readOnly = false;
  let routeFailure = false;
  await page.addInitScript(placesStub);
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    const json = url.pathname.endsWith('/mileage/maps')
      ? { browser_api_key: 'synthetic-not-a-provider-key', region_code: null, routes_available: true }
      : url.pathname.endsWith('/mileage/routes')
        ? routeFailure ? { outbound_miles: null, return_miles: null, error_code: 'quota' }
          : { outbound_miles: '12.4', return_miles: '14.6', error_code: null }
        : secondaryResponse(url, readOnly ? ['bookkeeping:read'] : undefined);
    return route.fulfill({ json });
  });
  async function capture(name: string) {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze()).violations).toEqual([]);
    await captureEvidence(page, test.info(), `${name}-${page.viewportSize()!.width}.png`);
  }
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await page.goto('/data');
    await expect(page.getByRole('button', { name: 'Download transactions CSV', exact: true })).toBeVisible();
    await expect(page.getByLabel('QuickBooks mileage CSV', { exact: true })).toBeVisible();
    await capture('integrated-exports-imports');
    await page.goto('/mixed-use/mixed/receipts');
    await expect(page.getByRole('heading', { name: 'Mixed-use receipts', exact: true })).toBeVisible();
    await expect(page.getByLabel('Receipt files')).toBeEnabled();
    await expect(page.getByRole('link', { name: /Download synthetic-receipt/ })).toBeVisible();
    await capture('integrated-mixed-receipts');
    await page.goto('/mileage/new');
    for (const [label, text] of [['Starting location lookup', 'Synthetic office'], ['Destination lookup', 'Synthetic client']]) {
      await page.getByRole('textbox', { name: label, exact: true }).fill(text);
      await page.getByRole('button', { name: 'Choose ' + label, exact: true }).click();
    }
    const calculate = page.getByRole('button', { name: 'Calculate mileage', exact: true });
    await expect(calculate).toBeEnabled();
    await expect(page.locator('.routeControls')).toHaveCSS('grid-column', '1 / -1');
    await calculate.click();
    await expect(page.getByLabel('Business miles', { exact: true })).toHaveValue('12.4');
    await expect(page.getByRole('checkbox', { name: 'I reviewed the recorded locations and mileage' })).toBeVisible();
    await capture('integrated-maps-review');
    routeFailure = true;
    await calculate.click();
    await expect(page.getByRole('alert').filter({ hasText: 'quota has been reached' })).toBeVisible();
    await expect(page.getByLabel('Business miles', { exact: true })).toHaveValue('12.4');
    await capture('integrated-maps-failure');
    routeFailure = false;
    // Use the supported guard before leaving an edited synthetic draft.
    await page.getByRole('link', { name: 'View mileage log', exact: true }).click();
    await page.getByRole('button', { name: 'Discard draft and leave', exact: true }).click();
  }
  readOnly = true;
  await page.goto('/mixed-use/mixed/receipts');
  await expect(page.getByLabel('Receipt files')).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Download synthetic-receipt/ })).toBeVisible();
  await capture('integrated-mixed-receipts-read-only');
});

test('file drop selects one mileage source and rejects a multi-file replacement without importing', async ({ page }) => {
  const mutations: string[] = [];
  await page.route('**/api/v1/**', route => {
    if (route.request().method() !== 'GET') mutations.push(route.request().url());
    return route.fulfill({ json: secondaryResponse(new URL(route.request().url())) });
  });
  await page.goto('/data');
  const input = page.getByLabel('QuickBooks mileage CSV', { exact: true });
  await expect(input).toBeVisible();
  async function drop(names: string[]) {
    await input.evaluate((element, filenames) => {
      const dataTransfer = new DataTransfer();
      for (const name of filenames) dataTransfer.items.add(new File(['synthetic'], name, { type: 'text/csv' }));
      element.parentElement!.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer }));
    }, names);
  }
  await drop(['trip.csv']);
  await expect(page.getByRole('button', { name: 'Preview mileage import', exact: true })).toBeEnabled();
  expect(await input.evaluate(element => (element as HTMLInputElement).files?.[0].name)).toBe('trip.csv');
  await drop(['other.csv', 'second.csv']);
  await expect(page.getByRole('alert')).toHaveText('Choose one file at a time.');
  expect(await input.evaluate(element => (element as HTMLInputElement).files?.[0].name)).toBe('trip.csv');
  expect(mutations).toEqual([]);
});

test('receipt drop stages files without upload and ignores further drops while the queue is unresolved', async ({ page }) => {
  const mutations: string[] = [];
  await page.route('**/api/v1/**', route => {
    if (route.request().method() !== 'GET') mutations.push(route.request().url());
    return route.fulfill({ json: secondaryResponse(new URL(route.request().url())) });
  });
  await page.goto('/mixed-use/mixed/receipts');
  const input = page.getByLabel('Receipt files');
  await expect(input).toBeEnabled();
  async function drop(name: string) {
    await input.evaluate((element, filename) => {
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(new File(['%PDF synthetic receipt'], filename, { type: 'application/pdf' }));
      element.parentElement!.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer }));
    }, name);
  }
  await drop('dropped.pdf');
  await expect(page.getByRole('list', { name: 'Selected receipts' })).toContainText('dropped.pdf: Upload pending');
  await expect(input).toBeDisabled();
  await drop('ignored.pdf');
  await expect(page.getByRole('list', { name: 'Selected receipts' })).not.toContainText('ignored.pdf');
  expect(mutations).toEqual([]);
});
