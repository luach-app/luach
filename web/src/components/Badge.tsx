import type { ReactNode } from 'react'
import type { HoldReason } from '../lib/types'
import { reasonLabel } from '../lib/labels'

type Tone = 'neutral' | 'accent' | 'success' | 'danger' | 'warn'

const tones: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-muted border-line-strong',
  accent: 'bg-accent/15 text-accent-text border-accent/30',
  success: 'bg-success/15 text-success border-success/30',
  danger: 'bg-danger/15 text-danger border-danger/30',
  warn: 'bg-[#f4b942]/10 text-accent-text border-accent/25',
}

export function Badge({ tone = 'neutral', children, className = '' }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium ${tones[tone]} ${className}`}>
      {children}
    </span>
  )
}

export function ReasonBadges({ reasons }: { reasons: HoldReason[] }) {
  if (!reasons?.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {reasons.map((r) => (
        <Badge key={r} tone="warn">
          {reasonLabel(r)}
        </Badge>
      ))}
    </div>
  )
}

const statuses: Record<string, [string, Tone]> = {
  pending: ['Waiting', 'accent'],
  running: ['Approving…', 'accent'],
  approved: ['Approved', 'success'],
  // Approved, but the call it ran was refused: nothing changed.
  failed: ['Not done', 'danger'],
  denied: ['Denied', 'danger'],
}

export function StatusBadge({ status }: { status: string }) {
  const [label, tone] = statuses[status] ?? [status, 'accent']
  return <Badge tone={tone}>{label}</Badge>
}
