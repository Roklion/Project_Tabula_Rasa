import createClient from 'openapi-fetch';
import type { components, paths } from './schema';

export type Session = components['schemas']['SessionInfo'];
export type Account = components['schemas']['Account'];
export type AccountCreate = components['schemas']['AccountCreate'];
export type ErrorCode = components['schemas']['ErrorCode'];
type Envelope = components['schemas']['ErrorEnvelope'];

export class ApiError extends Error {
  constructor(
    public readonly code: ErrorCode,
    public readonly requestId?: string,
    public readonly fields: components['schemas']['FieldError'][] = [],
  ) { super(code); }
}

export function unwrap<T>(result: { data?: T; error?: Envelope; response: Response }): T {
  if (result.error) {
    const error = result.error;
    throw new ApiError(error.error.code, error.request_id, error.error.fields ?? []);
  }
  if (!result.response.ok || result.data === undefined) {
    throw new ApiError('unexpected', result.response.headers.get('X-Request-ID') ?? undefined);
  }
  return result.data;
}

export function createApi(fetcher: typeof fetch = (...args) => fetch(...args)) {
  // Relative same-origin URLs only. Credentials/identity never enter localStorage.
  const client = createClient<paths>({ fetch: fetcher, credentials: 'same-origin' });
  const headers = (csrf?: string) => ({
    'X-Correlation-ID': crypto.randomUUID(),
    ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
  });
  const safe = async <T>(call: () => Promise<T>): Promise<T> => {
    try { return await call(); }
    catch (error) {
      if (error instanceof ApiError || (error instanceof DOMException && error.name === 'AbortError')) throw error;
      throw new ApiError('unavailable');
    }
  };
  return {
    session: (signal?: AbortSignal) => safe(async () => unwrap(await client.GET('/api/v1/session', { signal, headers: headers() }))),
    accounts: (session: Session, signal?: AbortSignal) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/accounts',
      { params: { path: { entity_id: session.entity.id }, query: { active_only: false } }, signal, headers: headers() },
    ))),
    createAccount: (session: Session, body: AccountCreate) => safe(async () => unwrap(await client.POST(
      '/api/v1/entities/{entity_id}/accounts',
      { params: { path: { entity_id: session.entity.id } }, body, headers: headers(session.csrf_token) },
    ))),
  };
}

export const api = createApi();
