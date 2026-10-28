export interface Member {
  id: number
  username: string
  email: string
  /** Every address, primary first (older servers omit it). */
  emails?: string[]
  /** Extra inboxes invited to every event this member creates (older servers omit it). */
  notify_emails?: string[]
  /** Added but not yet confirmed, so they receive nothing. */
  notify_pending?: string[]
  display_name: string
  timezone: string
  language: 'auto' | 'en' | 'es' | 'he' | string
  is_owner: boolean
  last_seen: string | null
  /** The model chosen in Settings; "" is the household's own (older servers omit it). */
  model?: string
}

/** POST /api/members/invite. Unsent, `link` is for the owner to pass on, and `mail` says why. */
export interface InviteResult {
  sent: boolean
  link?: string
  /** "not_configured": this luach sends no mail; "failed": it tried, and the server's log says why. */
  mail?: 'not_configured' | 'failed'
  /** Set when the link's address is not LUACH_APP_URL, or LUACH_APP_URL needs setting. */
  warning?: string
}

export interface MailInfo {
  enabled: boolean
  sender?: string
  own_domain?: boolean
  /** What mail cannot do here, in a sentence; "" when it works as it should. */
  limitation?: string
  /** The command that sets a member's password on the server, without mail. */
  offline_reset?: string
}

export interface SsoInfo {
  enabled: boolean
  label: string
}

export interface AuthStatus {
  users_exist: boolean
  authenticated: boolean
  member?: Member
  mail?: MailInfo
  sso?: SsoInfo
  /** The household's name for the sign-in screen; "" when it has none. */
  household?: string
}

export interface CalendarEvent {
  id: string
  title: string
  start: string
  end: string
  all_day: boolean
  location: string
  description: string
  /** The RRULE; on one occurrence of a repeating event, its series' rule. */
  recurrence: string[]
  /** On one occurrence of a repeating event, the series' id. */
  recurring_event_id: string
  /** One occurrence of a repeating event: a change or a delete asks "this one, or all?" (older servers omit it). */
  occurrence?: boolean
  html_link: string
  creator: string
  updated: string
  /** Which of the household's calendars holds it (older servers omit it). */
  calendar_id?: string
  /** Busy time from a read-only feed: shown, never edited. */
  read_only?: boolean
  /** Invited emails, the account itself excluded. */
  attendees?: string[]
  /** Set when the event was saved but the invitations could not be sent. */
  invite_error?: string
  /** The family member it is for (a Person key); '' when nobody's in particular. */
  leader?: string
  /** Everyone it is for; `leader` is the first of them. */
  leaders?: string[]
  /** Someone else's invitation: who sent it (only they can change it). */
  organizer?: string
}

/** Someone in the family. Not necessarily an account: the children may have none. */
export interface Person {
  key: string
  name: string
  /** Google Calendar event colorId, "1"–"11". */
  color: string
  hex: string
  kind: 'adult' | 'kid'
  email: string
  user_id: number | null
  position: number
}

export interface FamilyColor {
  id: string
  name: string
  hex: string
}

export interface Family {
  people: Person[]
  colors: FamilyColor[]
}

/** A to-do (once) or a chore (on weekdays), someone's. `done` is for the day asked about. */
export interface Task {
  id: number
  title: string
  /** A Person key; '' for whoever gets to it. */
  person: string
  due: string
  /** MO…SU for a chore; [] for a to-do. */
  days: string[]
  notes: string
  done: boolean
  overdue: boolean
  chore: boolean
}

export interface TaskInput {
  title: string
  person?: string
  due?: string
  days?: string[]
  notes?: string
}

/** One calendar the credential can see, flagged with what the household does with it. */
export interface CalendarInfo {
  id: string
  name: string
  color: string
  primary: boolean
  writable: boolean
  enabled: boolean
  default: boolean
}

export interface Household {
  calendars: string[]
  default_calendar: string
  default_attendees: string[]
}
export type HouseholdCalendars = Household & { available: CalendarInfo[] }

/**
 * The compact shape carried by widgets and `done.created`:
 * `{id, title, when, start, end, all_day?, location?, recurring?, description?, link?}`.
 * Tolerate partial rows and the full calendar shape alike.
 */
export type CompactEvent = Partial<CalendarEvent> & {
  title?: string
  start?: string
  /** Human line in the member's zone ("Fri 11 Sep 2026, 12:30–13:30"). */
  when?: string
  recurring?: boolean
  /** Google Calendar URL (the widget name for `html_link`). */
  link?: string
}

export interface AgendaWidget {
  kind: 'agenda'
  data: { title: string; events: CompactEvent[]; truncated?: boolean }
}
export interface AvailabilityWidget {
  kind: 'availability'
  data: { start: string; end: string; free: boolean; clashes: CompactEvent[] }
}
export interface EventWidget {
  kind: 'event'
  data: { event: CompactEvent }
}
export type Widget = AgendaWidget | AvailabilityWidget | EventWidget

/** When a member wants to hear about what is coming. */
export interface ReminderSettings {
  lead_minutes: number
  evening_hour: number
  /** Weekday for the week-ahead list, 0 = Monday, -1 = never. */
  weekly_day: number
  weekly_hour: number
  by_email: boolean
}

/** A read-only feed (the work calendar) luach reads busy time from. */
/** What a member's calendar feed holds: everyone's events, or theirs (and everyone's). */
export type FeedScope = 'household' | 'mine'

/** A member's calendar feed, as GET /api/feed has it. Never the link: the server keeps only its hash. */
export interface FeedStatus {
  enabled: boolean
  scope: FeedScope
  created_at: string | null
  last_read: string | null
}

/** Turn on and Reset: the status, and the link, this once. */
export interface FeedLink extends FeedStatus {
  url: string
  webcal: string
}

export interface BusySource {
  id: number
  name: string
  url: string
  enabled: boolean
  show_in_agenda: boolean
  last_fetched: string | null
  last_error: string
  blocks: number
}

export interface EmailRow {
  email: string
  added_at: string
  /** False until the confirmation link mailed to it is followed. */
  verified?: boolean
}
export interface EmailListing {
  primary: string
  emails: EmailRow[]
}

export interface Passkey {
  id: string
  name: string
  created_at: string
  last_used: string | null
}
export interface PasskeyListing {
  passkeys: Passkey[]
}
/** `{challenge_id, options}` — `options` is the browser's publicKey object with base64url fields. */
export interface PasskeyOptions<T = Record<string, unknown>> {
  challenge_id: string
  options: T
}

export interface StoredTurn {
  role: 'user' | 'assistant' | string
  content: string
  /** Widgets ride along as `{widget: {kind, data}}` entries. */
  events: unknown[]
  created_at: string
}
export interface ThreadSummary {
  id: string
  title: string
  door: string
  /** How many turns are in it, so an empty one can be told from a long one. */
  turns: number
  created_at: string
  updated_at: string
}

/** What a change or a delete of one occurrence acts on: that one, or every one. */
export type EventScope = 'this' | 'series'

export interface EventInput {
  title: string
  start: string
  end?: string
  location?: string
  description?: string
  /** One RRULE, '' for none, or a word of the Repeats menu ('weekly'…), which the server
   *  anchors on the event's own day. Sent only when the person changed how it repeats. */
  recurrence?: string
  /** Create only: one of the household's calendar ids; omitted = the default. */
  calendar_id?: string
  /** Omitted = the household's default invitees; [] = nobody. */
  attendees?: string[]
  /** A Person key; '' makes it nobody's. Omitted leaves it as it is. */
  leader?: string
  /** Everyone it is for; `leader` is the first of them. */
  leaders?: string[]
}

export interface InviteInfo {
  email: string
  inviter: string
  expires_at: string
}

export interface InviteRow {
  email: string
  created_at: string
  expires_at: string
  expired: boolean
}

export interface MembersResponse {
  members: Member[]
  invites: InviteRow[]
}

export type HoldReason = 'ambiguous' | 'past' | 'possible-duplicate' | 'mutation-existing' | 'from-your-email' | 'outside-the-house' | string

export interface PendingRow {
  id: string
  tool: string
  args: Record<string, unknown>
  summary: string
  reason: HoldReason[]
  principal: string
  door: string
  status: 'pending' | 'running' | 'approved' | 'failed' | 'denied' | string
  created_at: string
  decided_at: string | null
  decided_by: string | null
  result: unknown
  /** What a proposal was found in, when nobody asked for it (the email scan). */
  source?: HeldSource | null
}

export interface HeldSource {
  kind: 'email' | string
  /** The Gmail message id. */
  id: string
  subject: string
  from: string
  when: string
}

export interface AuditEntry {
  seq: number
  ts: string
  event_type: string
  payload: Record<string, unknown>
  hash: string
}

export interface AuditResponse {
  entries: AuditEntry[]
  total: number
  chain_verified: boolean
  head: string
}

export type StreamFrame =
  | { type: 'session'; thread_id: string }
  /** Which model is answering this turn. About now, not about the thread. */
  | { type: 'model'; name: string }
  | { type: 'token'; text: string }
  /** The words streamed so far are taken back: a later model call's words replace them. */
  | { type: 'retract' }
  | { type: 'thinking'; text: string }
  | { type: 'tool_start'; tool: string; args: Record<string, unknown> }
  | { type: 'tool_result'; tool: string; result: unknown; error?: string }
  /** A guide (skill) the model read before acting — named by its folder, e.g. "repeating-events". */
  | { type: 'skill'; name: string }
  | { type: 'held'; id: string; tool: string; summary: string; reason: HoldReason[]; reason_text: string }
  | ({ type: 'widget' } & Widget)
  | {
      type: 'done'
      reply: string
      thread_id: string
      tool_calls: unknown[]
      held: unknown[]
      created: CompactEvent[]
      widgets?: Widget[]
      /** The model that served the turn. */
      model?: string
    }
  | { type: 'error'; message: string }

/** Booking: what a member publishes, and what a visitor sees. */
export interface BookingSettings {
  enabled: boolean
  slug: string
  slot_minutes: number
  max_per_day: number
  buffer_minutes: number
  lead_hours: number
  horizon_days: number
  title: string
  location: string
  note: string
  /** Which of the household's calendars a booking lands on; '' = the default. */
  calendar_id: string
  /** Mail the member each time someone books. */
  notify_host: boolean
  /** 'zoom' creates a link per booking; 'none' uses the written location. */
  conferencing: 'none' | 'zoom' | string
  /** Whether the server has Zoom credentials at all (read-only). */
  zoom_ready?: boolean
  hours: Record<string, string[][]>
  link: string
  timezone: string
}

export interface BookingRow {
  start: string
  day: string
  name: string
  email: string
  note: string
  event_id: string
}

export interface BookingPage {
  host: string
  slug: string
  timezone: string
  slot_minutes: number
  note: string
  location: string
  days: { day: string; slots: { start: string; end: string }[] }[]
}

/** The meeting behind a confirmation link, as its guest sees it. */
export interface BookingManage {
  host: string
  slug: string
  timezone: string
  slot_minutes: number
  name: string
  start: string
  when: string
  cancelled: boolean
  past: boolean
  /** The zone the visitor booked in, when they gave one. */
  their_timezone?: string
  days: { day: string; slots: { start: string; end: string }[] }[]
}

export interface BookingTaken {
  booked: boolean
  /** False when the slot is held but no confirmation mail went out. */
  confirmation_sent?: boolean
  start: string
  end: string
  when: string
  host: string
  invite_error?: string
  /** Where the guest can move or cancel it later. */
  manage?: string
}

/** A fact luach keeps about the member (`/api/memory`). */
/** Settings › Your email: this member's own mailbox, never anyone else's. */
export interface MailStatus {
  connected: boolean
  /** The Gmail address, when connected here ('' for the household grant). */
  address: string
  /** 'own' — connected here; 'household' — the owner's mailbox the email door reads. */
  via: '' | 'own' | 'household'
  can_connect: boolean
  /** Reading new mail for things to propose (older servers omit it). */
  scan?: MailScan
  /** Google took the grant back (expired, revoked): which mailbox, and since when. Older servers omit it. */
  lost?: MailLost | null
}

export interface MailLost {
  address: string
  since: string
  /** 'own' — the member's own connection; 'household' — the email door's grant (the owner's). */
  via: 'own' | 'household'
}

export interface MailScan {
  /** Whether this luach runs the scan at all. */
  available: boolean
  enabled: boolean
  /** When it was turned on: mail from before is not read. */
  since: string
  /** How often it reads, in minutes. */
  minutes: number
  /** How many emails it has read, how many proposals came of them, and when it last read. */
  read?: number
  proposed?: number
  last_read?: string
}

export interface MemoryFact {
  key: string
  topic: string
  fact: string
  saved_at: string
}
