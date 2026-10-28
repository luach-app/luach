import { addDays } from './time'

/** "YYYY-MM" of a YYYY-MM-DD string. */
export const ymOf = (iso: string): string => iso.slice(0, 7)

export function addMonths(ym: string, n: number): string {
  const [y, m] = ym.split('-').map(Number)
  const t = new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1 + n, 1))
  return `${t.getUTCFullYear()}-${String(t.getUTCMonth() + 1).padStart(2, '0')}`
}

export const clampYear = (y: number): number => Math.min(9999, Math.max(1000, Math.trunc(y) || 1000))

/** Monday-based weekday index, 0 = Mon … 6 = Sun. */
export function weekdayMon(iso: string): number {
  return (new Date(`${iso}T12:00:00Z`).getUTCDay() + 6) % 7
}

export interface MonthGrid {
  ym: string
  /** First and last cell of the grid (Mon..Sun rows), inclusive. */
  first: string
  last: string
  weeks: string[][]
}

/** The Mon–Sun grid that covers `ym`, 4–6 rows. */
export function monthGrid(ym: string): MonthGrid {
  const first1 = `${ym}-01`
  const nextMonth = `${addMonths(ym, 1)}-01`
  const lastOfMonth = addDays(nextMonth, -1)
  const first = addDays(first1, -weekdayMon(first1))
  const last = addDays(lastOfMonth, 6 - weekdayMon(lastOfMonth))
  const weeks: string[][] = []
  for (let d = first; d <= last; d = addDays(d, 7)) {
    weeks.push(Array.from({ length: 7 }, (_, i) => addDays(d, i)))
  }
  return { ym, first, last, weeks }
}

const noon = (iso: string) => new Date(`${iso}T12:00:00Z`)

export function formatMonthYear(ym: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { timeZone: 'UTC', month: 'long', year: 'numeric' }).format(noon(`${ym}-01`))
}

export function formatMonthShort(month: number, locale: string): string {
  return new Intl.DateTimeFormat(locale, { timeZone: 'UTC', month: 'short' }).format(noon(`2024-${String(month).padStart(2, '0')}-01`))
}

/** Mon..Sun weekday labels in the locale (2024-01-01 is a Monday). */
export function weekdayNames(locale: string, style: 'short' | 'narrow' = 'short'): string[] {
  const fmt = new Intl.DateTimeFormat(locale, { timeZone: 'UTC', weekday: style })
  return Array.from({ length: 7 }, (_, i) => fmt.format(noon(addDays('2024-01-01', i))))
}
