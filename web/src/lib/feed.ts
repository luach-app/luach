/** When a calendar app last read a member's feed, as Settings says it. */
export const lastRead = (iso: string | null, now = Date.now()): string => {
  if (!iso) return 'not read by a calendar yet'
  const mins = Math.round((now - new Date(iso).getTime()) / 60000)
  if (mins < 2) return 'read just now'
  if (mins < 60) return `read ${mins} min ago`
  const hours = Math.round(mins / 60)
  return hours < 24 ? `read ${hours} h ago` : `read ${Math.round(hours / 24)} d ago`
}
