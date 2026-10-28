import type { StreamFrame } from '../lib/types'

const WRITE_TOOLS = new Set(['create_event', 'update_event', 'delete_event'])

/** Did this frame change what the calendar holds? */
export function changesTheCalendar(f: StreamFrame): boolean {
  if (f.type === 'tool_result') return WRITE_TOOLS.has(f.tool) && !f.error
  if (f.type === 'done') return Array.isArray(f.created) && f.created.length > 0
  return false
}
