import { useEffect, useState } from 'react'
import { control, errorMessage } from '../lib/api'
import type { AuditResponse } from '../lib/types'
import { formatTimestamp } from '../lib/time'
import { Badge } from './Badge'
import { Button, Spinner } from './Button'
import { Notice } from './Field'

function compactPayload(p: Record<string, unknown>): string {
  const bits: string[] = []
  for (const [k, v] of Object.entries(p ?? {})) {
    if (v == null || v === '') continue
    const s = typeof v === 'string' ? v : JSON.stringify(v)
    bits.push(`${k}=${s.length > 48 ? `${s.slice(0, 48)}…` : s}`)
    if (bits.length >= 4) break
  }
  return bits.join('  ')
}

export function Audit({ tz, locale }: { tz: string; locale: string }) {
  const [data, setData] = useState<AuditResponse | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    let alive = true
    control
      .audit(50)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(errorMessage(e)))
    return () => {
      alive = false
    }
  }, [open])

  return (
    <section className="card px-4 py-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">Audit</h2>
          <p className="text-sm text-muted">The tamper-evident log of what luach did.</p>
        </div>
        {!open ? (
          <Button size="sm" onClick={() => setOpen(true)}>
            Show
          </Button>
        ) : data ? (
          <Badge tone={data.chain_verified ? 'success' : 'danger'}>{data.chain_verified ? 'chain verified ✓' : 'chain broken ✗'}</Badge>
        ) : null}
      </div>
      {open ? (
        <div className="mt-3">
          {error ? <Notice kind="error">{error}</Notice> : null}
          {!data && !error ? (
            <div className="flex justify-center py-4 text-muted">
              <Spinner />
            </div>
          ) : null}
          {data ? (
            <>
              <div className="text-xs text-muted">
                {data.total} entries · showing the last {data.entries.length}
              </div>
              <ol className="mt-2 flex flex-col divide-y divide-[var(--border)]">
                {data.entries.map((e) => (
                  <li key={e.seq} className="py-2 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{e.event_type}</span>
                      <span className="shrink-0 text-xs text-muted">
                        #{e.seq} · {formatTimestamp(e.ts, tz, locale)}
                      </span>
                    </div>
                    <div className="truncate font-mono text-xs text-muted" dir="auto" title={compactPayload(e.payload)}>
                      {compactPayload(e.payload) || '—'}
                    </div>
                  </li>
                ))}
              </ol>
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
