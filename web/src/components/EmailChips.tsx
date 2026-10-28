import { useEffect, useId, useState, type KeyboardEvent } from 'react'
import { CloseIcon } from './Icons'

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const control =
  'w-full rounded-xl bg-surface-2 border border-line-strong px-3.5 py-2.5 text-[15px] placeholder:text-muted/70 focus-within:border-accent transition-colors'

interface Props {
  label: string
  value: string[]
  onChange: (next: string[]) => void
  hint?: string
  placeholder?: string
  disabled?: boolean
  /**
   * The address typed but not yet turned into a chip, when it is one ("" when
   * not). A form counts it as a change and saves it: someone who types one
   * address and reaches for Save has not thought to press Enter first.
   */
  onDraft?: (email: string) => void
}

const clean = (text: string) => text.trim().toLowerCase().replace(/[,;]$/, '')

/** A list of email addresses as removable chips; type one and press Enter, comma or space. */
export function EmailChips({ label, value, onChange, hint, placeholder = 'name@example.com', disabled, onDraft }: Props) {
  const [draft, setDraft] = useState('')
  const [bad, setBad] = useState(false)
  const noteId = useId()

  useEffect(() => {
    const email = clean(draft)
    // Saved by the form it sits in: it is a chip now, not a draft.
    if (email && value.includes(email)) setDraft('')
    else onDraft?.(EMAIL.test(email) ? email : '')
  }, [draft, value, onDraft])

  const commit = (): boolean => {
    const email = clean(draft)
    if (!email) return true
    if (!EMAIL.test(email)) {
      setBad(true)
      return false
    }
    if (!value.includes(email)) onChange([...value, email])
    setDraft('')
    setBad(false)
    return true
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',' || e.key === ' ' || e.key === ';') {
      e.preventDefault()
      commit()
    } else if (e.key === 'Backspace' && !draft && value.length) {
      onChange(value.slice(0, -1))
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm text-muted">{label}</span>
      <div className={`${control} flex flex-wrap items-center gap-1.5 ${bad ? 'border-danger' : ''}`}>
        {value.map((email) => (
          <span key={email} className="inline-flex max-w-full items-center gap-1 rounded-full border border-accent/30 bg-accent/15 py-1 ps-3 pe-1 text-sm text-accent-text" dir="ltr">
            <span className="truncate">{email}</span>
            <button type="button" aria-label={`Remove ${email}`} disabled={disabled} onClick={() => onChange(value.filter((e) => e !== email))} className="-me-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-accent/20 disabled:opacity-50">
              <CloseIcon width={16} height={16} />
            </button>
          </span>
        ))}
        <input
          type="email"
          value={draft}
          disabled={disabled}
          onChange={(e) => {
            setDraft(e.target.value)
            setBad(false)
          }}
          onKeyDown={onKey}
          onBlur={commit}
          placeholder={value.length ? '' : placeholder}
          aria-label={label}
          aria-describedby={bad || hint ? noteId : undefined}
          aria-invalid={bad || undefined}
          autoComplete="off"
          className="min-w-[10rem] flex-1 bg-transparent py-0.5 text-[15px] outline-none placeholder:text-muted/70"
          dir="ltr"
        />
      </div>
      {bad ? (
        <div id={noteId} className="text-xs text-danger">
          That is not an email address.
        </div>
      ) : hint ? (
        <div id={noteId} className="text-xs text-muted">
          {hint}
        </div>
      ) : null}
    </div>
  )
}
