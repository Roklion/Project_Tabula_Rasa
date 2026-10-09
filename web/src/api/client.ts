import createClient from 'openapi-fetch';
import type { components, paths } from './schema';

export type Session = components['schemas']['SessionInfo'];
export type Account = components['schemas']['Account'];
export type AccountCreate = components['schemas']['AccountCreate'];
export type ErrorCode = components['schemas']['ErrorCode'];
type Envelope = components['schemas']['ErrorEnvelope'];
export type Schemas = components['schemas'];

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
  const path = (session: Session, record_id: string) => ({ entity_id: session.entity.id, record_id });
  const listParams = (session: Session, signal?: AbortSignal) => ({ params: { path: { entity_id: session.entity.id } }, signal, headers: headers() });
  const mutationParams = (session: Session, id: string) => ({ params: { path: path(session, id) }, headers: headers(session.csrf_token) });
  const createParams = (session: Session) => ({ ...listParams(session), headers: headers(session.csrf_token) });
  return {
    session: (signal?: AbortSignal) => safe(async () => unwrap(await client.GET('/api/v1/session', { signal, headers: headers() }))),
    entities: (signal?: AbortSignal) => safe(async () => unwrap(await client.GET('/api/v1/entities', { signal, headers: headers() }))),
    selectEntity: (s: Session, entity_id: string) => safe(async () => unwrap(await client.POST('/api/v1/session/entity',
      { body: { entity_id }, headers: headers(s.csrf_token) }))),
    accounts: (session: Session, signal?: AbortSignal) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/accounts',
      { params: { path: { entity_id: session.entity.id }, query: { active_only: false } }, signal, headers: headers() },
    ))),
    createAccount: (session: Session, body: AccountCreate) => safe(async () => unwrap(await client.POST(
      '/api/v1/entities/{entity_id}/accounts',
      { params: { path: { entity_id: session.entity.id } }, body, headers: headers(session.csrf_token) },
    ))),
    updateAccount: (s: Session, id: string, body: Schemas['AccountUpdate']) => safe(async () => unwrap(await client.PATCH(
      '/api/v1/entities/{entity_id}/accounts/{record_id}', { ...mutationParams(s, id), body }))),
    deactivateAccount: (s: Session, id: string, baseline: string) => safe(async () => unwrap(await client.POST(
      '/api/v1/entities/{entity_id}/accounts/{record_id}/deactivate', { ...mutationParams(s, id), body: { baseline } }))),
    categories: (s: Session, signal?: AbortSignal) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/categories', listParams(s, signal)))),
    createCategory: (s: Session, body: Schemas['CategoryCreate']) => safe(async () => unwrap(await client.POST(
      '/api/v1/entities/{entity_id}/categories', { ...createParams(s), body }))),
    updateCategory: (s: Session, id: string, body: Schemas['CategoryUpdate']) => safe(async () => unwrap(await client.PATCH(
      '/api/v1/entities/{entity_id}/categories/{record_id}', { ...mutationParams(s, id), body }))),
    deleteCategory: (s: Session, id: string, baseline: string) => safe(async () => unwrap(await client.DELETE(
      '/api/v1/entities/{entity_id}/categories/{record_id}', { ...mutationParams(s, id), body: { baseline } }))),
    payees: (s: Session, signal?: AbortSignal) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/payees', listParams(s, signal)))),
    createPayee: (s: Session, body: Schemas['ManagedCreate']) => safe(async () => unwrap(await client.POST(
      '/api/v1/entities/{entity_id}/payees', { ...createParams(s), body }))),
    updatePayee: (s: Session, id: string, body: Schemas['ManagedUpdate']) => safe(async () => unwrap(await client.PATCH(
      '/api/v1/entities/{entity_id}/payees/{record_id}', { ...mutationParams(s, id), body }))),
    removePayee: (s: Session, id: string, baseline: string) => safe(async () => unwrap(await client.DELETE(
      '/api/v1/entities/{entity_id}/payees/{record_id}', { ...mutationParams(s, id), body: { baseline } }))),
    mergePayees: (s: Session, id: string, body: Schemas['ManagedMerge']) => safe(async () => unwrap(await client.POST(
      '/api/v1/entities/{entity_id}/payees/{record_id}/merge', { ...mutationParams(s, id), body }))),
    tags: (s: Session, signal?: AbortSignal) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/tags', listParams(s, signal)))),
    createTag: (s: Session, body: Schemas['ManagedCreate']) => safe(async () => unwrap(await client.POST(
      '/api/v1/entities/{entity_id}/tags', { ...createParams(s), body }))),
    updateTag: (s: Session, id: string, body: Schemas['ManagedUpdate']) => safe(async () => unwrap(await client.PATCH(
      '/api/v1/entities/{entity_id}/tags/{record_id}', { ...mutationParams(s, id), body }))),
    removeTag: (s: Session, id: string, baseline: string) => safe(async () => unwrap(await client.DELETE(
      '/api/v1/entities/{entity_id}/tags/{record_id}', { ...mutationParams(s, id), body: { baseline } }))),
    mergeTags: (s: Session, id: string, body: Schemas['ManagedMerge']) => safe(async () => unwrap(await client.POST(
      '/api/v1/entities/{entity_id}/tags/{record_id}/merge', { ...mutationParams(s, id), body }))),
    transactions: (s: Session, signal?: AbortSignal) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/transactions', listParams(s, signal)))),
    createTransaction: (s: Session, body: Schemas['TransactionCreate']) => safe(async () => unwrap(await client.POST(
      '/api/v1/entities/{entity_id}/transactions', { ...createParams(s), body }))),
    updateTransaction: (s: Session, id: string, body: Schemas['TransactionUpdate']) => safe(async () => unwrap(await client.PATCH(
      '/api/v1/entities/{entity_id}/transactions/{record_id}', { ...mutationParams(s, id), body }))),
    deleteTransaction: (s: Session, id: string, baseline: string) => safe(async () => unwrap(await client.DELETE(
      '/api/v1/entities/{entity_id}/transactions/{record_id}', { ...mutationParams(s, id), body: { baseline } }))),
    journals: (s: Session, signal?: AbortSignal) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/journals', listParams(s, signal)))),
    createJournal: (s: Session, body: Schemas['JournalCreate']) => safe(async () => unwrap(await client.POST(
      '/api/v1/entities/{entity_id}/journals', { ...createParams(s), body }))),
    ledger: (s: Session, filters: { start?: string; end?: string; kind?: 'All' | 'Income' | 'Expense' | 'Transfer' | 'Journal'; account_ids?: string[]; category_ids?: string[]; tag_ids?: string[] } = {}, signal?: AbortSignal) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/ledger', { ...listParams(s, signal), params: { path: { entity_id: s.entity.id }, query: filters } }))),
    reports: (s: Session, filters: { start?: string; end?: string } = {}, signal?: AbortSignal) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/reports/summary', { ...listParams(s, signal), params: { path: { entity_id: s.entity.id }, query: filters } }))),
    updateJournal: (s: Session, id: string, body: Schemas['JournalUpdate']) => safe(async () => unwrap(await client.PATCH(
      '/api/v1/entities/{entity_id}/journals/{record_id}', { ...mutationParams(s, id), body }))),
    deleteJournal: (s: Session, id: string, baseline: string) => safe(async () => unwrap(await client.DELETE(
      '/api/v1/entities/{entity_id}/journals/{record_id}', { ...mutationParams(s, id), body: { baseline } }))),
    mileage: (s: Session, signal?: AbortSignal) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/mileage', listParams(s, signal)))),
    mileageTrip: (s: Session, id: string, signal?: AbortSignal) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/mileage/{record_id}', { ...mutationParams(s, id), signal }))),
    createMileage: (s: Session, body: Schemas['MileageCreate']) => safe(async () => unwrap(await client.POST(
      '/api/v1/entities/{entity_id}/mileage', { ...listParams(s), body, headers: headers(s.csrf_token) }))),
    updateMileage: (s: Session, id: string, body: Schemas['MileageUpdate']) => safe(async () => unwrap(await client.PATCH(
      '/api/v1/entities/{entity_id}/mileage/{record_id}', { ...mutationParams(s, id), body }))),
    deleteMileage: (s: Session, id: string, baseline: string) => safe(async () => unwrap(await client.DELETE(
      '/api/v1/entities/{entity_id}/mileage/{record_id}', { ...mutationParams(s, id), body: { baseline } }))),
    unreferencedDocuments: (s: Session, signal?: AbortSignal) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/documents', listParams(s, signal)))),
    transactionDocuments: (s: Session, id: string, signal?: AbortSignal) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/transactions/{record_id}/receipts', { ...mutationParams(s, id), signal }))),
    uploadDocument: (s: Session, id: string, file: File) => safe(async () => unwrap(await client.PUT(
      '/api/v1/entities/{entity_id}/documents/{document_id}/content', {
        params: { path: { entity_id: s.entity.id, document_id: id }, query: { filename: file.name } },
        body: '', bodySerializer: () => file, headers: { ...headers(s.csrf_token), 'Content-Type': 'application/octet-stream' },
      }))),
    downloadDocument: (s: Session, document_id: string) => safe(async () => unwrap(await client.GET(
      '/api/v1/entities/{entity_id}/documents/{document_id}/content', {
        params: { path: { entity_id: s.entity.id, document_id } }, headers: headers(), parseAs: 'blob',
      }))),
    linkDocument: (s: Session, id: string, document_id: string) => safe(async () => unwrap(await client.POST(
      '/api/v1/entities/{entity_id}/transactions/{record_id}/receipts', { ...mutationParams(s, id), body: { document_id } }))),
    unlinkDocument: (s: Session, id: string, document_id: string) => safe(async () => unwrap(await client.DELETE(
      '/api/v1/entities/{entity_id}/transactions/{record_id}/receipts/{document_id}', {
        params: { path: { entity_id: s.entity.id, record_id: id, document_id } }, headers: headers(s.csrf_token),
      }))),
  };
}

export const api = createApi();
