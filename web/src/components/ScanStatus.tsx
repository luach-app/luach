import { useEffect, useState } from 'react'
import { mail as mailApi } from '../lib/api'
import type { MailScan } from '../lib/types'
import { scanLine } from '../lib/scan'

/** A line under Pending's heading, while this member's scan is on. */
export function ScanStatus({ tz, locale }: { tz: string; locale: string }) {
  const [scan, setScan] = useState<MailScan | null>(null)
  useEffect(() => {
    let alive = true
    mailApi.status().then(
      (st) => alive && setScan(st.connected && st.scan?.enabled ? st.scan : null),
      () => undefined,
    )
    return () => {
      alive = false
    }
  }, [])
  if (!scan) return null
  return (
    <p className="mt-1 flex items-center gap-2 text-xs text-muted">
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-success" />
      {scanLine(scan, tz, locale)}
    </p>
  )
}
