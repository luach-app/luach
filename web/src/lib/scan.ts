import type { MailScan } from './types'
import { formatTimestamp } from './time'

/**
 * The email scan, seen working. It read 120 emails and proposed 6 events before
 * anyone could tell it was running: nothing on any page said so.
 */
export function scanLine(scan: MailScan, tz: string, locale: string): string {
  const parts = [`Reading your email every ${scan.minutes} minutes`]
  if (scan.last_read) parts.push(`last ${formatTimestamp(scan.last_read, tz, locale)}`)
  if (scan.read !== undefined) parts.push(`${scan.read} read`)
  if (scan.proposed !== undefined) parts.push(`${scan.proposed} found`)
  return parts.join(' · ')
}
