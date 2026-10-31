import { expect, test } from '@playwright/test';
import type { Browser, BrowserContext } from '@playwright/test';
import { runRevocation } from '../session-revocation';
import type { RevocationTarget } from '../session-revocation';

test.use({ trace: 'off', screenshot: 'off', video: 'off' });
test.skip(({ browserName }) => browserName !== 'chromium', 'Standalone client uses Chromium.');
const requestId = 'b'.repeat(32);
const target = (): RevocationTarget => ({ origin: 'https://synthetic.invalid', release: 'a'.repeat(40),
  organization: 'org-a', business: 'business-a', controlOrganization: 'org-b', controlBusiness: 'business-b',
  approval: 'private-ref', synthetic: true, consent: true, readBudget: 10,
  expiresAt: new Date(Date.now() + 20 * 60_000).toISOString().replace(/\.\d{3}Z$/, 'Z') });

for (const scenario of ['success', 'wrong-release', 'wrong-business', 'same-actor-control', 'same-session',
  'changed-actor', 'held-still-authorized', 'control-denied', 'uncertain-post', 'failed-post',
  'oversized', 'malformed', 'redirect', 'cancel', 'expired', 'cleanup'] as const) {
  test(`three real isolated browser contexts: ${scenario}`, async ({ playwright }) => {
    const t = target();
    const native = await playwright.chromium.launch();
    let revoked = false;
    let changedActor = false;
    let posts = 0;
    let reads = 0;
    let closed = 0;
    let heldCookieAfter: string | undefined;
    const issued: string[] = [];
    const postHeaders: Record<string, string>[] = [];
    const browser = new Proxy(native, { get(object, key) {
      if (key !== 'newContext') {
        const value = Reflect.get(object, key);
        return typeof value === 'function' ? value.bind(object) : value;
      }
      return async (options: Parameters<Browser['newContext']>[0]) => {
        const index = issued.length;
        const cookie = `SENTINEL-session-${index}`;
        issued.push(cookie);
        const context = await object.newContext(options);
        const realRoute = context.route.bind(context);
        context.route = async (pattern, handler, routeOptions) => realRoute(pattern, async route => {
          // Synthetic transport replaces only continue(); actual browser cookies,
          // Origin, page evaluation, route budget and teardown are exercised.
          const transport = async () => {
            const request = route.request();
            const path = new URL(request.url()).pathname;
            if (path === '/api/v1/auth/login') return route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Fixture login</title>',
              headers: { 'set-cookie': `synthetic-session=${cookie}; Path=/; Secure; HttpOnly; SameSite=Lax` } });
            const headers = await request.allHeaders();
            expect(headers.cookie).toBe(`synthetic-session=${cookie}`);
            if (path === '/version') {
              reads++;
              return route.fulfill({ json: { release: scenario === 'wrong-release' ? 'c'.repeat(40) : t.release } });
            }
            if (path === '/api/v1/auth/revoke-all') {
              posts++;
              postHeaders.push(headers);
              if (scenario === 'failed-post') return route.fulfill({ status: 503, json: { private: 'SENTINEL' } });
              revoked = true;
              if (scenario === 'uncertain-post') return route.abort('connectionfailed');
              if (scenario === 'redirect') return route.fulfill({ status: 307, headers: { location: 'https://foreign.invalid/' } });
              return route.fulfill({ status: 204, headers: { 'x-request-id': requestId,
                'set-cookie': 'synthetic-session=; Path=/; Secure; HttpOnly; Max-Age=0' } });
            }
            expect(path).toBe('/api/v1/session');
            reads++;
            if (revoked && index === 1) heldCookieAfter = headers.cookie;
            const deny = revoked && (index === 1 && scenario !== 'held-still-authorized' || index === 2 && scenario === 'control-denied');
            if (deny) return route.fulfill({ status: 401, headers: { 'x-request-id': requestId },
              json: { error: { code: 'unauthorized', message: 'Sign in to continue.' }, request_id: requestId } });
            if (scenario === 'oversized') return route.fulfill({ contentType: 'application/json', body: ' '.repeat(65537) });
            if (scenario === 'malformed') return route.fulfill({ contentType: 'application/json', body: 'SENTINEL-invalid-json' });
            const isB = index === 2;
            return route.fulfill({ json: { state: 'ready', trusted_development: false,
              actor_id: isB && scenario !== 'same-actor-control' ? 'SENTINEL-B' : changedActor ? 'SENTINEL-changed' : 'SENTINEL-A',
              cache_scope: scenario === 'same-session' && index === 1 ? 'SENTINEL-cache-0' : `SENTINEL-cache-${index}`,
              organization_id: isB ? t.controlOrganization : t.organization,
              entity: { id: scenario === 'wrong-business' ? 'wrong' : isB ? t.controlBusiness : t.business,
                organization_id: isB ? t.controlOrganization : t.organization, role: 'owner' },
              csrf_token: `SENTINEL-csrf-${index}`, capabilities: [] } });
          };
          const facade = new Proxy(route, { get(r, property) {
            if (property === 'continue') return transport;
            const value = Reflect.get(r, property);
            return typeof value === 'function' ? value.bind(r) : value;
          } });
          await handler(facade, route.request());
        }, routeOptions);
        const realClose = context.close.bind(context);
        context.close = async () => { await realClose(); closed++; if (scenario === 'cleanup' && index === 0) throw Error('SENTINEL'); };
        return context as BrowserContext;
      };
    } }) as Browser;
    try {
      const outcome = await runRevocation(t, async () => browser, async step => {
        if (step === 'revoke') {
          if (scenario === 'changed-actor') changedActor = true;
          if (scenario === 'expired') t.expiresAt = '2020-01-01T00:00:00Z';
          if (scenario === 'cancel') return false;
        }
        return true;
      });
      expect(JSON.stringify(outcome)).not.toContain('SENTINEL');
      expect(outcome.collector_and_notification).toBe('unverified');
      expect(native.isConnected()).toBe(false);
      expect(closed).toBe(3);
      const beforePost = ['wrong-release', 'wrong-business', 'same-actor-control', 'same-session', 'changed-actor', 'oversized', 'malformed', 'cancel', 'expired'].includes(scenario);
      expect(posts).toBe(beforePost ? 0 : 1);
      expect(reads).toBeLessThanOrEqual(10);
      if (posts) {
        expect(postHeaders[0].origin).toBe(t.origin);
        expect(postHeaders[0]['x-csrf-token']).toBe('SENTINEL-csrf-0');
      }
      if (scenario === 'success') {
        expect(outcome).toMatchObject({ status: 'passed', phase: 'complete', release: t.release,
          revocation: 'confirmed', held_session_denied: true, control_authorized: true,
          revoke_request_id: requestId, denial_request_id: requestId });
        expect(reads).toBe(10);
        expect(heldCookieAfter).toBe('synthetic-session=SENTINEL-session-1');
      } else {
        expect(outcome.status).toBe('stopped');
        if (scenario === 'uncertain-post' || scenario === 'failed-post' || scenario === 'redirect') expect(outcome.revocation).toBe('unconfirmed');
        if (scenario === 'held-still-authorized') expect(outcome.held_session_denied).toBe(false);
        if (scenario === 'control-denied') expect(outcome.control_authorized).toBe(false);
      }
    } finally { await native.close(); }
  });
}
