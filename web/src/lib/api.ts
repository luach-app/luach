import type {
  MailStatus,
  MemoryFact,
  AuditResponse,
  AuthStatus,
  BookingManage,
  BookingPage,
  BusySource,
  FeedLink,
  FeedScope,
  FeedStatus,
  ReminderSettings,
  BookingRow,
  BookingSettings,
  BookingTaken,
  CalendarEvent,
  EmailListing,
  EventInput,
  EventScope,
  Family,
  Household,
  HouseholdCalendars,
  InviteInfo,
  InviteResult,
  Member,
  MembersResponse,
  PasskeyListing,
  PasskeyOptions,
  PendingRow,
  Person,
  StoredTurn,
  Task,
  TaskInput,
  ThreadSummary,
} from './types'
import type { CatalogueAnswer, ManagedModel, ModelHealth, ModelsSnapshot, ModelTrial } from './models'

export class ApiError extends Error {
  status: number
  retryAfter?: number
  constructor(status: number, message: string, retryAfter?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.retryAfter = retryAfter
  }
}

let unauthorizedHandler: (() => void) | null = null
/** App installs this once; any 401 outside the gate sends the user back to sign-in. */
export function setUnauthorizedHandler(fn: (() => void) | null) {
  unauthorizedHandler = fn
}

/** Where a successful write can change what the calendar shows. */
const CALENDAR_WRITES = ['/api/calendar', '/api/control', '/api/tasks', '/api/booking', '/api/household', '/api/busy', '/api/family']
const writeListeners = new Set<(path: string) => void>()

/**
 * Hear about every successful write that may change the calendar — an approve, a
 * deny, an edit, wherever in the app it was made. The month cache listens, so a
 * change made on one screen is not stale on the next. Returns the unsubscribe.
 */
export function onCalendarWrite(fn: (path: string) => void): () => void {
  writeListeners.add(fn)
  return () => {
    writeListeners.delete(fn)
  }
}

interface RequestOptions {
  /** Do not treat a 401 as "session lost" (used by the login form itself). */
  quiet401?: boolean
  signal?: AbortSignal
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts: RequestOptions = {},
): Promise<T> {
  const init: RequestInit = {
    method,
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
    signal: opts.signal,
  }
  if (body !== undefined) {
    init.headers = { ...init.headers, 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  const res = await fetch(path, init)
  const out = await handle<T>(res, opts)
  if (method !== 'GET' && CALENDAR_WRITES.some((prefix) => path.startsWith(prefix))) {
    for (const fn of writeListeners) fn(path)
  }
  return out
}

async function handle<T>(res: Response, opts: RequestOptions): Promise<T> {
  let data: unknown = null
  const text = await res.text()
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }
  if (!res.ok) {
    const obj = (data ?? {}) as { error?: string; retry_after?: number }
    const message = obj.error || fallbackMessage(res.status)
    if (res.status === 401 && !opts.quiet401) unauthorizedHandler?.()
    throw new ApiError(res.status, message, obj.retry_after)
  }
  return data as T
}

function fallbackMessage(status: number): string {
  if (status === 401) return 'Please sign in again.'
  if (status === 403) return 'You are not allowed to do that.'
  if (status === 404) return 'Not found.'
  if (status === 429) return 'Too many attempts. Please wait a moment.'
  if (status >= 500) return 'luach hit a problem on the server.'
  return `Request failed (${status}).`
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>('GET', path, undefined, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>('POST', path, body ?? {}, opts),
  patch: <T>(path: string, body: unknown, opts?: RequestOptions) =>
    request<T>('PATCH', path, body, opts),
  put: <T>(path: string, body: unknown, opts?: RequestOptions) => request<T>('PUT', path, body, opts),
  del: <T>(path: string, opts?: RequestOptions) => request<T>('DELETE', path, undefined, opts),
}

/* ---- auth --------------------------------------------------------------- */
export const auth = {
  status: () => api.get<AuthStatus>('/api/auth/status', { quiet401: true }),
  register: (b: {
    username: string
    email: string
    password: string
    display_name?: string
    /** The one-time code the server prints to its log while it has no accounts. */
    setup_code: string
    /** IANA zone the owner starts in (the browser's, unless they changed it). */
    timezone?: string
  }) => api.post<Member>('/api/auth/register', b),
  login: (username: string, password: string) =>
    api.post<Member>('/api/auth/login', { username, password }, { quiet401: true }),
  logout: () => api.post<{ ok: boolean }>('/api/auth/logout'),
  me: () => api.get<Member>('/api/auth/me'),
  update: (b: Partial<Pick<Member, 'display_name' | 'timezone' | 'language' | 'notify_emails' | 'model'>>) =>
    api.patch<Member>('/api/auth/me', b),
  password: (current: string, next: string) =>
    api.post<{ ok: boolean }>('/api/auth/password', { current, new: next }),
  forgot: (email: string) => api.post<{ ok: boolean }>('/api/auth/forgot', { email }),
  reset: (token: string, password: string) =>
    api.post<Member>('/api/auth/reset', { token, password }),
  invite: (token: string) =>
    api.get<InviteInfo>(`/api/auth/invite/${encodeURIComponent(token)}`, { quiet401: true }),
  accept: (b: { token: string; username: string; password: string; display_name?: string; timezone?: string }) =>
    api.post<Member>('/api/auth/accept', b),
}

/* ---- emails (every call answers with the same listing) ------------------ */
export const emails = {
  list: () => api.get<EmailListing>('/api/auth/emails'),
  add: (email: string) => api.post<EmailListing>('/api/auth/emails', { email }),
  remove: (email: string) => api.del<EmailListing>(`/api/auth/emails/${encodeURIComponent(email)}`),
  primary: (email: string) => api.post<EmailListing>('/api/auth/emails/primary', { email }),
  resend: (email: string) => api.post<{ sent: boolean; email: string }>('/api/auth/emails/resend', { email }),
  verify: (token: string) => api.post<{ email: string; kind: string }>('/api/auth/verify', { token }, { quiet401: true }),
}

/* ---- passkeys (WebAuthn) ------------------------------------------------ */
export const passkeys = {
  list: () => api.get<PasskeyListing>('/api/auth/passkeys'),
  registerOptions: () => api.post<PasskeyOptions>('/api/auth/passkeys/register/options'),
  registerVerify: (b: { challenge_id: string; credential: unknown; name?: string }) =>
    api.post<PasskeyListing>('/api/auth/passkeys/register/verify', b),
  remove: (id: string) => api.del<PasskeyListing>(`/api/auth/passkeys/${encodeURIComponent(id)}`),
  loginOptions: () => api.post<PasskeyOptions>('/api/auth/passkeys/login/options', {}, { quiet401: true }),
  loginVerify: (b: { challenge_id: string; credential: unknown }) =>
    api.post<Member>('/api/auth/passkeys/login/verify', b, { quiet401: true }),
}

/* ---- members ------------------------------------------------------------ */
export const members = {
  list: () => api.get<MembersResponse>('/api/members'),
  invite: (email: string) => api.post<InviteResult>('/api/members/invite', { email }),
  remove: (id: number) => api.del<{ ok: boolean }>(`/api/members/${id}`),
  revoke: (email: string) =>
    api.del<{ ok: boolean; revoked: number }>(`/api/members/invite/${encodeURIComponent(email)}`),
}

/* ---- calendar ----------------------------------------------------------- */
const eventPath = (id: string, calendarId?: string, scope?: EventScope) => {
  const q = new URLSearchParams()
  if (calendarId) q.set('calendar', calendarId)
  if (scope) q.set('scope', scope)
  return `/api/calendar/events/${encodeURIComponent(id)}${q.size ? `?${q}` : ''}`
}

export const calendar = {
  list: (start: string, end: string, signal?: AbortSignal) =>
    api.get<{ events: CalendarEvent[]; timezone: string }>(
      `/api/calendar/events?start=${start}&end=${end}`,
      { signal },
    ),
  get: (id: string, calendarId?: string) => api.get<CalendarEvent>(eventPath(id, calendarId)),
  create: (b: EventInput) => api.post<CalendarEvent>('/api/calendar/events', b),
  update: (id: string, b: Partial<EventInput>, calendarId?: string, scope?: EventScope) =>
    api.patch<CalendarEvent>(eventPath(id, calendarId, scope), b),
  remove: (id: string, calendarId?: string, scope?: EventScope) => api.del<{ ok: boolean }>(eventPath(id, calendarId, scope)),
}

/* ---- booking (mine needs a session; the page and take are public) ------- */
export const booking = {
  mine: () => api.get<BookingSettings>('/api/booking'),
  update: (b: Partial<BookingSettings>) => api.patch<BookingSettings>('/api/booking', b),
  upcoming: () => api.get<{ bookings: BookingRow[] }>('/api/booking/upcoming'),
  page: (slug: string) => api.get<BookingPage>(`/api/book/${encodeURIComponent(slug)}`, { quiet401: true }),
  take: (slug: string, b: { start: string; name: string; email: string; note?: string; timezone?: string }) =>
    api.post<BookingTaken>(`/api/book/${encodeURIComponent(slug)}`, b, { quiet401: true }),
  manage: (slug: string, token: string) =>
    api.get<BookingManage>(`/api/book/${encodeURIComponent(slug)}/manage/${encodeURIComponent(token)}`, { quiet401: true }),
  cancel: (slug: string, token: string) =>
    api.post<{ cancelled: boolean; already?: boolean }>(`/api/book/${encodeURIComponent(slug)}/manage/${encodeURIComponent(token)}/cancel`, {}, { quiet401: true }),
  move: (slug: string, token: string, start: string) =>
    api.post<{ moved: boolean; when: string; start: string }>(`/api/book/${encodeURIComponent(slug)}/manage/${encodeURIComponent(token)}/move`, { start }, { quiet401: true }),
}

/* ---- reminders ---------------------------------------------------------- */
export const reminders = {
  get: () => api.get<ReminderSettings>('/api/reminders'),
  update: (b: Partial<ReminderSettings>) => api.patch<ReminderSettings>('/api/reminders', b),
}

/* ---- busy feeds (the work calendar, read-only) -------------------------- */
export const busy = {
  list: () => api.get<{ sources: BusySource[] }>('/api/busy'),
  add: (b: { name: string; url: string; show_in_agenda?: boolean }) =>
    api.post<{ sources: BusySource[] }>('/api/busy', b),
  update: (id: number, b: Partial<Pick<BusySource, 'enabled' | 'show_in_agenda' | 'name'>>) =>
    api.patch<{ sources: BusySource[] }>(`/api/busy/${id}`, b),
  remove: (id: number) => api.del<{ sources: BusySource[] }>(`/api/busy/${id}`),
  refresh: () => api.post<{ read: number; sources: BusySource[] }>('/api/busy/refresh'),
}

/* ---- the member's calendar feed (their phone's own calendar app) --------- */
export const calendarFeed = {
  status: () => api.get<FeedStatus>('/api/feed'),
  turnOn: (scope: FeedScope) => api.post<FeedLink>('/api/feed', { scope }),
  reset: () => api.post<FeedLink>('/api/feed/reset'),
  change: (scope: FeedScope) => api.patch<FeedStatus>('/api/feed', { scope }),
  turnOff: () => api.del<FeedStatus>('/api/feed'),
}

/* ---- the model menu (the owner's) --------------------------------------- */
export const models = {
  manage: () => api.get<ModelsSnapshot>('/api/models/manage'),
  add: (b: { id: string; name?: string; about?: string; local?: boolean; provider?: string; try?: boolean }) =>
    api.post<ModelsSnapshot & { added: string; trial_started: boolean; note: string }>('/api/models/manage', b),
  edit: (b: { id: string; name?: string; about?: string; provider?: string; enabled?: boolean; local?: boolean }) =>
    api.patch<ModelsSnapshot>('/api/models/manage', b),
  remove: (id: string) => api.post<ModelsSnapshot>('/api/models/manage/remove', { id }),
  order: (ids: string[]) => api.put<ModelsSnapshot>('/api/models/manage/order', { ids }),
  setDefault: (id: string) => api.put<ModelsSnapshot>('/api/models/manage/default', { id }),
  trial: () => api.get<{ trial: ModelTrial | null; trials_left_today: number }>('/api/models/manage/trial'),
  tryIt: (id: string) =>
    api.post<{ trial: ModelTrial | null; trials_left_today: number }>('/api/models/manage/trial', { id }),
  cancelTrial: () => api.post<{ cancelled: boolean; trial: ModelTrial | null }>('/api/models/manage/trial/cancel', {}),
  check: (id: string) =>
    api.post<{ ok: boolean; reason: string; health: ModelHealth | null; models: ManagedModel[] }>('/api/models/manage/check', { id }),
  catalogue: (q: string, signal?: AbortSignal) =>
    api.get<CatalogueAnswer>(`/api/models/catalogue?q=${encodeURIComponent(q)}`, { signal }),
}

/* ---- household (calendars, default calendar, default invitees) ---------- */
export const household = {
  get: () => api.get<Household>('/api/household'),
  calendars: (signal?: AbortSignal) => api.get<HouseholdCalendars>('/api/household/calendars', { signal }),
  update: (b: Partial<Household>) => api.patch<Household>('/api/household', b),
}

/* ---- family (who events and tasks belong to) ----------------------------- */
type PersonInput = Partial<Pick<Person, 'name' | 'kind' | 'color' | 'email' | 'position'>>
export const family = {
  get: () => api.get<Family>('/api/family'),
  add: (b: PersonInput & { name: string }) => api.post<Person>('/api/family', b),
  update: (key: string, b: PersonInput) => api.patch<Person>(`/api/family/${encodeURIComponent(key)}`, b),
  remove: (key: string) => api.del<{ ok: boolean }>(`/api/family/${encodeURIComponent(key)}`),
}

/* ---- tasks (anyone ticks; the grown-ups decide) --------------------------- */
export const tasks = {
  day: (day?: string) => api.get<{ day: string; tasks: Task[]; may_assign: boolean }>(`/api/tasks${day ? `?day=${day}` : ''}`),
  add: (b: TaskInput) => api.post<Task>('/api/tasks', b),
  update: (id: number, b: Partial<TaskInput>) => api.patch<Task>(`/api/tasks/${id}`, b),
  remove: (id: number) => api.del<{ ok: boolean }>(`/api/tasks/${id}`),
  tick: (id: number, day: string, done: boolean) => api.post<Task>(`/api/tasks/${id}/done`, { day, done }),
}

/* ---- threads ------------------------------------------------------------ */
export const threads = {
  list: () => api.get<{ threads: ThreadSummary[]; retention_days: number }>('/api/threads'),
  rename: (id: string, title: string) =>
    api.patch<{ id: string; title: string }>(`/api/threads/${encodeURIComponent(id)}`, { title }),
  get: (id: string, signal?: AbortSignal) =>
    api.get<{ turns: StoredTurn[] }>(`/api/threads/${encodeURIComponent(id)}`, { signal }),
  remove: (id: string) => api.del<{ ok: boolean }>(`/api/threads/${encodeURIComponent(id)}`),
}

/* ---- control ------------------------------------------------------------ */
export const control = {
  pending: (all = false, signal?: AbortSignal) =>
    api.get<{ pending: PendingRow[] }>(`/api/control/pending${all ? '?all=1' : ''}`, { signal }),
  approve: (id: string) => api.post<PendingRow>(`/api/control/pending/${encodeURIComponent(id)}/approve`),
  deny: (id: string) => api.post<PendingRow>(`/api/control/pending/${encodeURIComponent(id)}/deny`),
  audit: (limit = 50) => api.get<AuditResponse>(`/api/control/audit?limit=${limit}`),
}

/* ---- voice + push ------------------------------------------------------- */
export const voice = {
  status: () => api.get<{ available: boolean }>('/api/transcribe/status'),
  transcribe: async (blob: Blob, contentType: string): Promise<{ text: string }> => {
    const res = await fetch('/api/transcribe', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': contentType, Accept: 'application/json' },
      body: blob,
    })
    return handle<{ text: string }>(res, {})
  },
}

/* ---- what luach remembers about you ------------------------------------ */
export const memory = {
  list: () => api.get<{ facts: MemoryFact[] }>('/api/memory'),
  add: (fact: string) => api.post<{ facts: MemoryFact[] }>('/api/memory', { fact }),
  remove: (key: string) => api.del<{ ok: boolean; facts: MemoryFact[] }>(`/api/memory/${encodeURIComponent(key)}`),
}

export const mail = {
  status: () => api.get<MailStatus>('/api/mail'),
  disconnect: () => api.del<MailStatus & { ok: boolean }>('/api/mail'),
  scan: (enabled: boolean) => api.patch<MailStatus>('/api/mail/scan', { enabled }),
}

export const push = {
  key: () => api.get<{ public_key: string }>('/api/push/key'),
  subscribe: (subscription: PushSubscriptionJSON) =>
    api.post<unknown>('/api/push/subscribe', { subscription }),
  unsubscribe: (endpoint: string) => api.post<unknown>('/api/push/unsubscribe', { endpoint }),
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429 && err.retryAfter) {
      return `${err.message} Try again in ${Math.ceil(err.retryAfter)} s.`
    }
    return err.message
  }
  // A cancelled request is not news; one that ran out of time is.
  if (err instanceof DOMException && err.name === 'TimeoutError') {
    return 'That took too long to answer. Check the connection and try again.'
  }
  if (err instanceof DOMException && err.name === 'AbortError') return ''
  if (err instanceof Error) return err.message || 'Something went wrong.'
  return 'Something went wrong.'
}
