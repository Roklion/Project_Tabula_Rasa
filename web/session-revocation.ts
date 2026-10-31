// Standalone operator client; never imported by the application bundle.
import { randomBytes } from 'node:crypto';
import { parseArgs } from 'node:util';
import { pathToFileURL } from 'node:url';
import { createInterface } from 'node:readline/promises';
import type { Browser, BrowserContext, Page, Route } from '@playwright/test';
import { guard, validateTarget } from './support-denial.ts';
import type { Target } from './support-denial.ts';

export type RevocationTarget = Target & { controlOrganization: string; controlBusiness: string;
  expiresAt: string; readBudget: number };
type Identity = { actor: string; session: string };
type ProbeInput = { target: RevocationTarget; scope: 'a' | 'b'; salt: string;
  operation: 'inspect' | 'revoke' | 'denial' | 'control'; expected?: Identity };
type ProbeResult = { ok: boolean; identity?: Identity; request_id?: string;
  post: 'not_sent' | 'unconfirmed' | 'confirmed' };
export type Outcome = { status: 'stopped' | 'passed'; phase: string; release: string | null;
  revocation: ProbeResult['post']; revoke_request_id: string | null; denial_request_id: string | null;
  held_session_denied: boolean; control_authorized: boolean;
  collector_and_notification: 'unverified' };
const initial = (): Outcome => ({ status: 'stopped', phase: 'preflight', release: null,
  revocation: 'not_sent', revoke_request_id: null, denial_request_id: null,
  held_session_denied: false, control_authorized: false, collector_and_notification: 'unverified' });

async function restrict(route: Route, operation: () => Promise<void>) {
  try { await operation(); }
  catch { try { await route.abort('blockedbyclient'); } catch { /* Browser already closed. */ } }
}

export function validateRevocationTarget(target: RevocationTarget, now = Date.now()) {
  validateTarget(target);
  validateTarget({ ...target, organization: target.controlOrganization, business: target.controlBusiness });
  const expires = Date.parse(target.expiresAt);
  if (target.readBudget !== 10 || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(target.expiresAt)
    || !Number.isFinite(expires) || expires <= now || expires - now > 30 * 60_000) throw Error('refused');
}

export type Budget = { reads: number; postAvailable: boolean; postTaken: boolean };
export async function loginGuard(route: Route, target: RevocationTarget, budget: { reads: number; selections: number }) {
  const request = route.request();
  const url = new URL(request.url());
  if (Date.now() >= Date.parse(target.expiresAt)) return route.abort('blockedbyclient');
  if (url.origin === target.origin && url.pathname.startsWith('/api/')) {
    if (request.method() === 'GET' && ++budget.reads > 30) return route.abort('blockedbyclient');
    if (request.method() === 'POST' && url.pathname === '/api/v1/session/entity' && ++budget.selections > 4) return route.abort('blockedbyclient');
  }
  return guard(route, target.origin, '/api/v1/auth/revoke-all', () => false);
}

export async function probeGuard(route: Route, target: RevocationTarget, invoking: boolean, budget: Budget) {
  const request = route.request();
  const url = new URL(request.url());
  if (url.origin !== target.origin || url.search || Date.now() >= Date.parse(target.expiresAt)) return route.abort('blockedbyclient');
  if (request.isNavigationRequest() && request.method() === 'GET' && url.pathname === '/') {
    return route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Operator verification</title>' });
  }
  if (request.method() === 'GET' && ['/version', '/api/v1/session'].includes(url.pathname) && budget.reads < target.readBudget) {
    budget.reads++; return route.continue();
  }
  if (invoking && budget.postAvailable && !budget.postTaken && request.method() === 'POST'
    && url.pathname === '/api/v1/auth/revoke-all') {
    budget.postTaken = true; budget.postAvailable = false; return route.continue();
  }
  return route.abort('blockedbyclient');
}

// Self-contained for page.evaluate serialization. Only fixed operations exist;
// cookies, CSRF, session DTOs and raw errors never leave their browser context.
export async function revocationProbe(input: ProbeInput): Promise<ProbeResult> {
  const result: ProbeResult = { ok: false, post: 'not_sent' };
  const { target, operation } = input;
  try {
    if (location.origin !== target.origin || !target.synthetic || !target.consent
      || Date.now() >= Date.parse(target.expiresAt)) return result;
    const read = async (path: '/version' | '/api/v1/session' | '/api/v1/auth/revoke-all', method = 'GET', csrf?: string) => {
      if (Date.now() >= Date.parse(target.expiresAt)) throw Error('refused');
      if (method === 'POST') result.post = 'unconfirmed'; // Never retry an uncertain mutation.
      const response = await fetch(target.origin + path, { method, credentials: 'same-origin', redirect: 'error',
        cache: 'no-store', signal: AbortSignal.timeout(Math.max(1, Math.min(15000, Date.parse(target.expiresAt) - Date.now()))),
        headers: csrf ? { 'X-CSRF-Token': csrf } : {} });
      if (response.url !== target.origin + path || response.redirected) {
        await response.body?.cancel(); throw Error('refused');
      }
      const id = response.headers.get('x-request-id');
      const request_id = typeof id === 'string' && /^[a-f0-9]{32}$/.test(id) ? id : undefined;
      if (method === 'POST') {
        await response.body?.cancel();
        return { status: response.status, request_id, data: null };
      }
      if (response.headers.get('content-type')?.split(';')[0].trim() !== 'application/json' || !response.body) {
        await response.body?.cancel(); throw Error('refused');
      }
      const reader = response.body.getReader();
      const chunks: Uint8Array[] = [];
      let size = 0;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.length;
          if (size > 65536) throw Error('refused');
          chunks.push(value);
        }
      } finally { await reader.cancel(); }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      return { status: response.status, request_id,
        data: JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) };
    };
    if (operation === 'inspect' || operation === 'revoke') {
      const version = await read('/version');
      if (version.status !== 200 || version.data?.release !== target.release) return result;
    }
    const reply = await read('/api/v1/session');
    if (operation === 'denial') {
      const data = reply.data;
      if (reply.status === 401 && reply.request_id && data?.request_id === reply.request_id
        && Object.keys(data).sort().join(',') === 'error,request_id'
        && data.error?.code === 'unauthorized' && data.error.message === 'Sign in to continue.'
        && Object.keys(data.error).sort().join(',') === 'code,message') {
        result.ok = true; result.request_id = reply.request_id;
      }
      return result;
    }
    const s = reply.data;
    const organization = input.scope === 'a' ? target.organization : target.controlOrganization;
    const business = input.scope === 'a' ? target.business : target.controlBusiness;
    if (reply.status !== 200 || s?.state !== 'ready' || s.trusted_development !== false
      || s.organization_id !== organization || s.entity?.id !== business || s.entity.organization_id !== organization
      || !['owner', 'admin', 'editor', 'accountant', 'read_only'].includes(s.entity.role)
      || typeof s.actor_id !== 'string' || !s.actor_id || typeof s.cache_scope !== 'string' || !s.cache_scope
      || typeof s.csrf_token !== 'string' || !/^[\x21-\x7e]{1,512}$/.test(s.csrf_token)
      || !Array.isArray(s.capabilities) || !s.capabilities.every((v: unknown) => typeof v === 'string')) return result;
    const tag = async (kind: string, value: string) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',
      new TextEncoder().encode(JSON.stringify([input.salt, kind, value])))), b => b.toString(16).padStart(2, '0')).join('');
    const identity = { actor: await tag('actor', s.actor_id), session: await tag('session', s.cache_scope) };
    if (input.expected && (identity.actor !== input.expected.actor || identity.session !== input.expected.session)) return result;
    if (operation === 'inspect') return { ...result, ok: true, identity };
    if (operation === 'control') return { ...result, ok: !!input.expected };
    if (operation !== 'revoke' || input.scope !== 'a' || !input.expected) return result;
    const post = await read('/api/v1/auth/revoke-all', 'POST', s.csrf_token);
    if (post.status === 204 && post.request_id) {
      result.post = 'confirmed'; result.request_id = post.request_id; result.ok = true;
    }
  } catch { /* Never expose a body, exception, actor, CSRF, cookie or provider URL. */ }
  return result;
}

export async function runRevocation(target: RevocationTarget, launch: () => Promise<Browser>,
  confirm: (step: 'invoking-a' | 'held-a' | 'control-b' | 'revoke') => Promise<boolean>): Promise<Outcome> {
  const result = initial();
  const contexts: BrowserContext[] = [];
  let browser: Browser | undefined;
  const budget: Budget = { reads: 0, postAvailable: false, postTaken: false };
  try {
    validateRevocationTarget(target);
    browser = await launch();
    const pages: Page[] = [];
    for (const step of ['invoking-a', 'held-a', 'control-b'] as const) {
      result.phase = step;
      const context = await browser.newContext({ acceptDownloads: false, serviceWorkers: 'block' });
      contexts.push(context);
      const loginBudget = { reads: 0, selections: 0 };
      await context.route('**/*', route => restrict(route, () => loginGuard(route, target, loginBudget)));
      const login = await context.newPage();
      await login.goto(target.origin + '/api/v1/auth/login');
      if (!await confirm(step) || Date.now() >= Date.parse(target.expiresAt)) return result;
      // Stop SPA timers without clearing the held browser's cookies. New blank
      // same-origin documents below run only our fixed probes, not financial UI.
      for (const page of context.pages()) await page.close();
      await context.unroute('**/*');
      await context.route('**/*', route => restrict(route, () => probeGuard(route, target, step === 'invoking-a', budget)));
      const page = await context.newPage();
      await page.goto(target.origin + '/');
      pages.push(page);
    }
    const salt = randomBytes(32).toString('hex');
    const probe = (index: number, input: ProbeInput) => pages[index].evaluate(revocationProbe, input);
    const snapshots: Identity[] = [];
    result.phase = 'identity-check';
    for (let i = 0; i < pages.length; i++) {
      const p = await probe(i, { target, salt, scope: i === 2 ? 'b' : 'a', operation: 'inspect' });
      if (!p.ok || !p.identity) return result;
      snapshots.push(p.identity);
    }
    if (snapshots[0].actor !== snapshots[1].actor || snapshots[0].session === snapshots[1].session
      || snapshots[0].actor === snapshots[2].actor) return result;
    result.release = target.release;
    result.phase = 'consent';
    if (!await confirm('revoke') || Date.now() >= Date.parse(target.expiresAt)) return result;
    result.phase = 'revoke';
    budget.postAvailable = true;
    const revoked = await probe(0, { target, salt, scope: 'a', operation: 'revoke', expected: snapshots[0] });
    budget.postAvailable = false;
    result.revocation = revoked.post;
    if (!revoked.ok) return result;
    result.revoke_request_id = revoked.request_id ?? null;
    result.phase = 'held-denial';
    const denied = await probe(1, { target, salt, scope: 'a', operation: 'denial' });
    result.held_session_denied = denied.ok;
    result.denial_request_id = denied.request_id ?? null;
    result.phase = 'control-read';
    const control = await probe(2, { target, salt, scope: 'b', operation: 'control', expected: snapshots[2] });
    result.control_authorized = control.ok;
    if (denied.ok && control.ok && budget.reads === target.readBudget && budget.postTaken) {
      result.status = 'passed'; result.phase = 'complete';
    }
  } catch {
    if (budget.postTaken && result.revocation === 'not_sent') result.revocation = 'unconfirmed';
  } finally {
    budget.postAvailable = false;
    for (const context of contexts) { try { await context.close(); } catch { result.status = 'stopped'; } }
    try { await browser?.close(); } catch { result.status = 'stopped'; }
  }
  return result;
}

export async function main(argv = process.argv.slice(2)) {
  let result = initial();
  try {
    if (process.execArgv.length || Object.keys(process.env).some(k => /^(DEBUG|PWDEBUG|NODE_DEBUG|NODE_OPTIONS|PW_LOG_NAME|PLAYWRIGHT_)/.test(k)
      && process.env[k])) throw Error('refused');
    const { values } = parseArgs({ args: argv, options: {
      origin: { type: 'string' }, release: { type: 'string' }, organization: { type: 'string' }, business: { type: 'string' },
      'control-organization': { type: 'string' }, 'control-business': { type: 'string' }, approval: { type: 'string' },
      'expires-at': { type: 'string' }, 'read-budget': { type: 'string' },
      'synthetic-approved': { type: 'boolean' }, 'consent-one-revocation': { type: 'boolean' },
    } });
    const target: RevocationTarget = { origin: values.origin ?? '', release: values.release ?? '',
      organization: values.organization ?? '', business: values.business ?? '',
      controlOrganization: values['control-organization'] ?? '', controlBusiness: values['control-business'] ?? '',
      approval: values.approval ?? '', expiresAt: values['expires-at'] ?? '', readBudget: Number(values['read-budget']),
      synthetic: values['synthetic-approved'] === true, consent: values['consent-one-revocation'] === true };
    validateRevocationTarget(target);
    if (!process.stdin.isTTY || !process.stdout.isTTY) throw Error('refused');
    const { chromium } = await import('@playwright/test');
    result = await runRevocation(target, () => chromium.launch({ headless: false }), async step => {
      const terminal = createInterface({ input: process.stdin, output: process.stdout });
      const phrase = step === 'revoke' ? 'SEND ONE USER-WIDE REVOCATION' : `READY ${step.toUpperCase()}`;
      try {
        return await terminal.question(step === 'revoke'
          ? `Confirm external exact-target/window approval, user-wide A1/A2 impact and independent B control. Type ${phrase}: `
          : `Complete normal login/MFA for ${step} and select its approved business. No credentials in this terminal. Type ${phrase}: `,
        { signal: AbortSignal.timeout(Math.max(1, Date.parse(target.expiresAt) - Date.now())) }) === phrase;
      } finally { terminal.close(); }
    });
  } catch { /* Sanitized fixed output only, including parse/launch/cleanup failures. */ }
  console.log(JSON.stringify(result));
  return result.status === 'passed' ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) process.exitCode = await main();
