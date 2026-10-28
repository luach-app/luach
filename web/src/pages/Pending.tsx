import { useCallback, useState } from 'react'
import { control, errorMessage } from '../lib/api'
import type { Member, PendingRow } from '../lib/types'
import { formatTimestamp, resolveLocale } from '../lib/time'
import { useVisiblePoll } from '../lib/hooks'
import { ApprovalCard } from '../components/ApprovalCard'
import { Spinner } from '../components/Button'
import { Notice } from '../components/Field'
import { ScanStatus } from '../components/ScanStatus'

export function Pending({ member, onHoldsChanged }: { member: Member; onHoldsChanged: () => void }) {
  const tz = member.timezone || 'UTC'
  const locale = resolveLocale(member.language)
  const [all, setAll] = useState(false)
  const [rows, setRows] = useState<PendingRow[] | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await control.pending(all)
      setRows(res.pending)
      setError('')
    } catch (e) {
      setError(errorMessage(e))
    }
  }, [all])

  useVisiblePoll(load, 30_000)

  const decided = (row: PendingRow) => {
    setRows((prev) => (prev ?? []).map((r) => (r.id === row.id ? row : r)))
    onHoldsChanged()
  }

  const shown = (rows ?? []).filter((r) => all || r.status === 'pending')
  return (
    <div className="fade-up">
      <header className="flex items-end justify-between px-1">
        <div>
          <h1 className="text-2xl font-semibold">Pending</h1>
          <p className="text-sm text-muted">Held actions from every member and door.</p>
          <ScanStatus tz={tz} locale={locale} />
        </div>
        <label className="flex items-center gap-2 text-sm text-muted">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} className="h-5 w-5 shrink-0 accent-[var(--accent)]" />
          Show decided
        </label>
      </header>
      {error ? (
        <div className="mt-4">
          <Notice kind="error">{error}</Notice>
        </div>
      ) : null}
      <div className="mt-5 flex flex-col gap-3">
        {rows === null && !error ? (
          <div className="flex justify-center py-10 text-muted">
            <Spinner />
          </div>
        ) : shown.length === 0 ? (
          <div className="card px-5 py-8 text-center text-muted">{all ? 'No held actions yet.' : 'Nothing waiting for approval.'}</div>
        ) : (
          shown.map((r) => (
            <ApprovalCard
              key={r.id}
              item={r}
              tz={tz}
              locale={locale}
              onDecided={decided}
              meta={[
                r.principal ? `by ${r.principal}` : '',
                r.door ? `via ${r.door}` : '',
                r.created_at ? formatTimestamp(r.created_at, tz, locale) : '',
                r.decided_by ? `${r.status} by ${r.decided_by}` : '',
              ]
                .filter(Boolean)
                .join(' · ')}
            />
          ))
        )}
      </div>
    </div>
  )
}
