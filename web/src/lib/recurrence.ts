/** Repeats, as a person says them — and as Google needs them. */

export type Repeat = 'none' | 'daily' | 'weekly' | 'biweekly' | 'monthly' | 'yearly' | 'custom'

const DAYS = ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA']

const body = (rules: string[] | undefined): string =>
  (rules ?? []).find((r) => r.toUpperCase().includes('FREQ='))?.toUpperCase().replace(/^RRULE:/, '') ?? ''

/** Which of the offered repeats this event already is; 'custom' when it is
 *  something luach's menu cannot say, which is then left untouched. */
export function repeatOf(rules: string[] | undefined): Repeat {
  const rule = body(rules)
  if (!rule) return 'none'
  const has = (k: string) => rule.includes(k)
  const interval = /INTERVAL=(\d+)/.exec(rule)?.[1]
  const plain = !has('COUNT=') && !has('UNTIL=') && !has('BYMONTHDAY=') && !has('BYSETPOS=')
  if (!plain) return 'custom'
  if (has('FREQ=DAILY') && !interval) return 'daily'
  if (has('FREQ=WEEKLY') && (!interval || interval === '1')) return 'weekly'
  if (has('FREQ=WEEKLY') && interval === '2') return 'biweekly'
  if (has('FREQ=MONTHLY') && !interval) return 'monthly'
  if (has('FREQ=YEARLY') && !interval) return 'yearly'
  return 'custom'
}

/** What the form sends for a choice: the menu's own word, which the server makes into a
 *  rule on the event's own day in the member's zone. '' = no repeat.
 *  The weekday used to be worked out here, from `new Date('2026-09-17')`: that is
 *  midnight UTC, the evening before west of UTC, so a weekly all-day event made in
 *  New York repeated on the wrong day. */
export function repeatWord(repeat: Repeat): string {
  return repeat === 'none' || repeat === 'custom' ? '' : repeat
}

/** "Every week on Tuesday" rather than "RRULE:FREQ=WEEKLY;BYDAY=TU". */
export function describeRepeat(rules: string[] | undefined, locale = 'en'): string {
  const rule = body(rules)
  if (!rule) return ''
  const named = /BYDAY=([A-Z,]+)/.exec(rule)?.[1]
  const weekdays = named
    ? named
        .split(',')
        .map((d) => {
          const index = DAYS.indexOf(d.slice(-2))
          if (index < 0) return d
          const sample = new Date(Date.UTC(2024, 0, 7 + index)) // a Sunday, then on
          return new Intl.DateTimeFormat(locale, { weekday: 'long', timeZone: 'UTC' }).format(sample)
        })
        .join(', ')
    : ''
  const every = /INTERVAL=(\d+)/.exec(rule)?.[1]
  const unit = rule.includes('FREQ=DAILY')
    ? 'day'
    : rule.includes('FREQ=WEEKLY')
      ? 'week'
      : rule.includes('FREQ=MONTHLY')
        ? 'month'
        : rule.includes('FREQ=YEARLY')
          ? 'year'
          : ''
  if (!unit) return rule
  const head = every && every !== '1' ? `Every ${every} ${unit}s` : `Every ${unit}`
  const times = /COUNT=(\d+)/.exec(rule)?.[1]
  const until = /UNTIL=(\d{8})/.exec(rule)?.[1]
  const tail = times
    ? `, ${times} times`
    : until
      ? `, until ${until.slice(0, 4)}-${until.slice(4, 6)}-${until.slice(6, 8)}`
      : ''
  return head + (weekdays ? ` on ${weekdays}` : '') + tail
}
