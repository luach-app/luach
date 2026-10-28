import type { CompactEvent } from './types'

/** The Google Calendar URL under either name the API uses. */
export const eventLink = (ev: CompactEvent): string => ev.html_link || ev.link || ''

export const isRecurring = (ev: CompactEvent): boolean => !!ev.recurring || !!ev.recurring_event_id || !!ev.recurrence?.length

/** One occurrence of a repeating event (not the series itself): a change or a delete asks which. */
export const isOccurrence = (ev: { occurrence?: boolean; recurring_event_id?: string }): boolean => !!ev.occurrence || !!ev.recurring_event_id
