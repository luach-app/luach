import type { Person, Task } from './types'

const DAY_LABEL: Record<string, string> = { MO: 'Mon', TU: 'Tue', WE: 'Wed', TH: 'Thu', FR: 'Fri', SA: 'Sat', SU: 'Sun' }

export function describeDays(days: string[]): string {
  if (days.length === 7) return 'every day'
  if (days.join() === 'MO,TU,WE,TH,FR') return 'weekdays'
  if (days.join() === 'SA,SU') return 'weekends'
  return days.map((d) => DAY_LABEL[d] ?? d).join(', ')
}

export interface Column {
  key: string
  name: string
  hex: string
  tasks: Task[]
}

/** One column per person, in the family's order, then whoever-gets-to-it. */
export function columnsFor(people: Person[], list: Task[]): Column[] {
  const known = new Set(people.map((p) => p.key))
  const cols: Column[] = people.map((p) => ({ key: p.key, name: p.name, hex: p.hex, tasks: list.filter((t) => t.person === p.key) }))
  const anyone = list.filter((t) => !t.person || !known.has(t.person))
  if (anyone.length) cols.push({ key: '', name: 'Anyone', hex: '', tasks: anyone })
  return cols
}
