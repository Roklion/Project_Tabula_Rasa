import { expect, test } from '@playwright/test';
import type { Browser, Route } from '@playwright/test';
import { loginGuard, main, probeGuard, runRevocation, validateRevocationTarget } from '../session-revocation';
import type { Budget, RevocationTarget } from '../session-revocation';

const target = (): RevocationTarget => ({ origin: 'https://synthetic.invalid', release: 'a'.repeat(40),
  organization: 'org-a', business: 'business-a', controlOrganization: 'org-b', controlBusiness: 'business-b',
  approval: 'private-ref', synthetic: true, consent: true, readBudget: 10,
  expiresAt: new Date(Date.now() + 20 * 60_000).toISOString().replace(/\.\d{3}Z$/, 'Z') });

test('target, finite window and exact read budget fail closed before browser launch', async () => {
  for (const delta of [{ synthetic: false }, { consent: false }, { approval: '' }, { release: 'main' },
    { origin: 'http://synthetic.invalid' }, { controlBusiness: '../wrong' }, { readBudget: 11 },
    { expiresAt: 'not-a-time' }, { expiresAt: '2020-01-01T00:00:00Z' }, { expiresAt: '2099-01-01T00:00:00Z' }]) {
    let launches = 0;
    const result = await runRevocation({ ...target(), ...delta }, async () => { launches++; throw Error('SENTINEL'); }, async () => true);
    expect(launches).toBe(0);
    expect(result.revocation).toBe('not_sent');
    expect(result.status).toBe('stopped');
  }
  expect(() => validateRevocationTarget(target())).not.toThrow();
});

test('probe guard enforces total reads, invoking-only one-shot POST and same-origin fixed routes', async () => {
  const t = target();
  const budget: Budget = { reads: 0, postAvailable: false, postTaken: false };
  const decisions: string[] = [];
  async function check(path: string, method: string, invoking = true, navigation = false) {
    const route = { request: () => ({ url: () => path.startsWith('https:') ? path : t.origin + path,
      method: () => method, isNavigationRequest: () => navigation }),
    continue: async () => { decisions.push('allowed'); }, abort: async () => { decisions.push('blocked'); },
    fulfill: async () => { decisions.push('local'); } } as unknown as Route;
    await probeGuard(route, t, invoking, budget);
  }
  await check('/', 'GET', true, true);
  await check('/api/v1/entities/business-a/accounts', 'GET');
  await check('/api/v1/auth/revoke-all', 'POST');
  budget.postAvailable = true;
  await check('/api/v1/auth/revoke-all', 'POST', false);
  await check('/api/v1/auth/revoke-all', 'POST');
  await check('/api/v1/auth/revoke-all', 'POST');
  await check('https://foreign.invalid/api/v1/session', 'GET');
  await check('/api/v1/session?extra=1', 'GET');
  for (let i = 0; i < 11; i++) await check('/api/v1/session', 'GET');
  t.expiresAt = '2020-01-01T00:00:00Z';
  await check('/', 'GET', true, true);
  expect(decisions).toEqual(['local', 'blocked', 'blocked', 'blocked', 'allowed', 'blocked',
    'blocked', 'blocked', ...Array(10).fill('allowed'), 'blocked', 'blocked']);
  expect(budget).toEqual({ reads: 10, postAvailable: false, postTaken: true });
});

test('CLI parse/debug failures print only the fixed sanitized outcome', async () => {
  const output: string[] = [];
  const original = console.log;
  console.log = value => output.push(String(value));
  try {
    expect(await main(['--cookie', 'SENTINEL-secret'])).toBe(1);
    expect(await main(['--origin', 'https://SENTINEL-secret@synthetic.invalid'])).toBe(1);
  } finally { console.log = original; }
  expect(output).toHaveLength(2);
  for (const line of output) {
    expect(JSON.parse(line)).toMatchObject({ status: 'stopped', phase: 'preflight', revocation: 'not_sent',
      collector_and_notification: 'unverified' });
    expect(line).not.toContain('SENTINEL');
  }
});

test('login guard bounds API reads and selections and never permits revocation', async () => {
  const t = target();
  const budget = { reads: 0, selections: 0 };
  const decisions: string[] = [];
  async function call(path: string, method: string) {
    await loginGuard({ request: () => ({ url: () => t.origin + path, method: () => method }),
      continue: async () => { decisions.push('allowed'); }, abort: async () => { decisions.push('blocked'); } } as unknown as Route,
    t, budget);
  }
  for (let i = 0; i < 31; i++) await call('/api/v1/session', 'GET');
  for (let i = 0; i < 5; i++) await call('/api/v1/session/entity', 'POST');
  await call('/api/v1/auth/revoke-all', 'POST');
  t.expiresAt = '2020-01-01T00:00:00Z';
  await call('/api/v1/auth/login', 'GET');
  expect(decisions).toEqual([...Array(30).fill('allowed'), 'blocked', ...Array(4).fill('allowed'), 'blocked', 'blocked', 'blocked']);
});

test('early login refusal closes created context and browser without a probe or mutation', async () => {
  const closed: string[] = [];
  const browser = { newContext: async () => ({ route: async () => {},
    newPage: async () => ({ goto: async () => {} }), close: async () => { closed.push('context'); } }),
  close: async () => { closed.push('browser'); } } as unknown as Browser;
  const outcome = await runRevocation(target(), async () => browser, async () => false);
  expect(outcome).toMatchObject({ status: 'stopped', phase: 'invoking-a', revocation: 'not_sent' });
  expect(closed).toEqual(['context', 'browser']);
});
