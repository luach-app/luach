import { useState } from 'react'
import { clampYear, formatMonthShort } from '../../lib/months'
import { Button } from '../../components/Button'
import { Sheet } from '../../components/Sheet'

interface Props {
  ym: string
  todayYm: string
  locale: string
  onPick: (ym: string) => void
  onClose: () => void
}

/** Year stepper (typable) + a 3×4 month grid; any year 1000–9999. */
export function MonthPicker({ ym, todayYm, locale, onPick, onClose }: Props) {
  const [year, setYear] = useState(Number(ym.slice(0, 4)))
  const [draft, setDraft] = useState(String(year))
  const setBoth = (y: number) => {
    const c = clampYear(y)
    setYear(c)
    setDraft(String(c))
  }
  const commitDraft = () => setBoth(Number(draft))
  const pick = (m: number) => onPick(`${String(year).padStart(4, '0')}-${String(m).padStart(2, '0')}`)

  return (
    <Sheet open title="Go to" onClose={onClose}>
      <div className="flex items-center justify-center gap-2">
        <Button size="icon" variant="ghost" aria-label="Previous year" onClick={() => setBoth(year - 1)}>
          ‹
        </Button>
        <input
          type="number"
          inputMode="numeric"
          aria-label="Year"
          min={1000}
          max={9999}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitDraft}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              commitDraft()
            }
          }}
          className="w-24 rounded-xl border border-line-strong bg-surface-2 px-3 py-2 text-center text-lg font-semibold tabular-nums focus:border-accent focus:outline-none"
        />
        <Button size="icon" variant="ghost" aria-label="Next year" onClick={() => setBoth(year + 1)}>
          ›
        </Button>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2" role="group" aria-label="Month">
        {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
          const key = `${String(year).padStart(4, '0')}-${String(m).padStart(2, '0')}`
          const current = key === ym
          const today = key === todayYm
          return (
            <button
              key={m}
              type="button"
              onClick={() => pick(m)}
              aria-current={current ? 'date' : undefined}
              className={`h-11 rounded-xl border text-sm font-medium transition-colors ${current ? 'border-accent bg-accent text-accent-on' : today ? 'border-accent/50 bg-surface-2 text-text' : 'border-line bg-surface-2 text-text hover:border-accent/50'}`}
            >
              {formatMonthShort(m, locale)}
            </button>
          )
        })}
      </div>
    </Sheet>
  )
}
