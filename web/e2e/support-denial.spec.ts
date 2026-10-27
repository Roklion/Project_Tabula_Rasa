import { expect, test } from '@playwright/test';
import { probe } from '../support-denial';

test.use({ trace: 'off', screenshot: 'off', video: 'off' });
// The standalone operator launches Chromium only. WebKit's intercepted requests
// omit cookie headers and cannot fulfill redirects; they are not its transport.
test.skip(({ browserName }) => browserName !== 'chromium', 'Operator client uses Chromium only.');
const target = { origin: 'https://synthetic.invalid', release: 'a'.repeat(40), organization: 'org-a',
  business: 'business-a', approval: 'private-ref', synthetic: true, consent: true };
const requestId = 'b'.repeat(32);
const session = { state: 'ready', actor_id: 'synthetic-user', organization_id: 'org-a',
  entity: { id: 'business-a', organization_id: 'org-a', name: 'Synthetic', role: 'read_only' },
  cache_scope: 'synthetic-scope', csrf_token: 'SENTINEL-csrf', trusted_development: false, capabilities: [] };
const forbidden = { error: { code: 'forbidden', message: 'You do not have access to this operation.' }, request_id: requestId };

for (const business of ['business-a', 'business-b']) {
test(`expected denial for ${business} uses isolated cookies, Origin and in-memory CSRF exactly once`, async ({ page, context }) => {
  const selected = { ...target, business };
  const posts: { path: string; origin?: string; csrf?: string; cookie?: string; body: unknown }[] = [];
  expect(await context.cookies()).toEqual([]);
  await context.addCookies([{ name: 'synthetic-session', value: `SENTINEL-${business}`, url: target.origin }]);
  await context.route('**/*', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST') {
      const headers = await request.allHeaders();
      posts.push({ path, origin: headers.origin, csrf: headers['x-csrf-token'], cookie: headers.cookie, body: request.postDataJSON() });
    }
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<html></html>' });
    await route.fulfill({ status: path.endsWith('/diagnostics') ? 403 : 200, contentType: 'application/json',
      headers: { 'x-request-id': requestId }, body: JSON.stringify(path === '/version' ? { release: target.release }
        : path === '/api/v1/session' ? { ...session, entity: { ...session.entity, id: business } } : forbidden) });
  });
  await page.goto(target.origin);
  const result = await page.evaluate(probe, selected);
  expect(result).toEqual({ status: 'expected_forbidden', release: target.release,
    request_id: requestId, collector_and_notification: 'unverified' });
  expect(posts).toEqual([{ path: `/api/v1/support/org-a/${business}/diagnostics`, origin: target.origin,
    csrf: 'SENTINEL-csrf', cookie: `synthetic-session=SENTINEL-${business}`, body: { reason: 'incident' } }]);
  expect(JSON.stringify(result)).not.toContain('SENTINEL');
});
}

for (const scenario of ['consent', 'wrong-origin', 'release', 'anonymous', 'alpha', 'setup', 'business-b',
  'organization-b', 'missing-csrf', 'malformed-session', 'redirect', 'success', 'upstream', 'malformed',
  'oversized', 'unsafe-id', 'extra-secret', 'wrong-code', 'transport'] as const) {
  test(`refuses ${scenario} without leaking contents or retrying`, async ({ page, context }) => {
    let posts = 0;
    await context.route('**/*', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<html></html>' });
      if (path === '/version') return route.fulfill({ json: { release: scenario === 'release' ? 'c'.repeat(40) : target.release } });
      if (path === '/api/v1/session') {
        if (scenario === 'anonymous') return route.fulfill({ status: 401, json: { secret: 'SENTINEL-secret' } });
        const data = structuredClone(session);
        if (scenario === 'alpha') data.trusted_development = true;
        if (scenario === 'setup') data.state = 'needs_setup';
        if (scenario === 'business-b') data.entity.id = 'business-b';
        if (scenario === 'organization-b') data.organization_id = 'org-b';
        if (scenario === 'missing-csrf') data.csrf_token = '';
        return route.fulfill({ json: scenario === 'malformed-session' ? null : data });
      }
      posts++;
      if (scenario === 'transport') return route.abort('connectionfailed');
      if (scenario === 'redirect') return route.fulfill({ status: 307, headers: { location: 'https://foreign.invalid/' } });
      const data = structuredClone(forbidden);
      if (scenario === 'unsafe-id') data.request_id = 'SENTINEL-secret';
      if (scenario === 'wrong-code') data.error.code = 'unauthorized';
      const body = scenario === 'malformed' ? 'SENTINEL-secret' : scenario === 'oversized' ? ' '.repeat(65537)
        : JSON.stringify(scenario === 'extra-secret' ? { ...data, secret: 'SENTINEL-secret' } : data);
      await route.fulfill({ status: scenario === 'success' ? 200 : scenario === 'upstream' ? 502 : 403,
        contentType: 'application/json', headers: { 'x-request-id': requestId }, body });
    });
    await page.goto(target.origin);
    const result = await page.evaluate(probe, { ...target, consent: scenario !== 'consent',
      origin: scenario === 'wrong-origin' ? 'https://foreign.invalid' : target.origin });
    expect(result.status).toBe('refused');
    expect(result.request_id).toBeNull();
    expect(JSON.stringify(result)).not.toContain('SENTINEL');
    expect(posts).toBe(['redirect', 'success', 'upstream', 'malformed', 'oversized', 'unsafe-id',
      'extra-secret', 'wrong-code', 'transport'].includes(scenario) ? 1 : 0);
  });
}
