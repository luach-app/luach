import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { useId } from 'react'
import { ChevronDownIcon } from './Icons'

const control =
  'w-full rounded-xl bg-surface-2 border border-line-strong px-3.5 py-2.5 text-[15px] placeholder:text-muted/70 focus:border-accent focus:outline-none transition-colors'

interface FieldProps {
  label: string
  hint?: ReactNode
  /** The control, given its id and what describes it (the hint's id, when there is one). */
  children: (id: string, describedBy: string | undefined) => ReactNode
  className?: string
}

export function Field({ label, hint, children, className = '' }: FieldProps) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <label htmlFor={id} className="text-sm text-muted">
        {label}
      </label>
      {children(id, hintId)}
      {hint ? (
        <div id={hintId} className="text-xs text-muted">
          {hint}
        </div>
      ) : null}
    </div>
  )
}

/** The hint, and anything the caller already said describes the control. */
const describedBy = (hintId: string | undefined, own: string | undefined) => [own, hintId].filter(Boolean).join(' ') || undefined

type InputProps = InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode }
export function Input({ label, hint, className = '', ...rest }: InputProps) {
  return (
    <Field label={label} hint={hint} className={className}>
      {(id, hintId) => <input id={id} {...rest} aria-describedby={describedBy(hintId, rest['aria-describedby'])} className={control} />}
    </Field>
  )
}

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint?: ReactNode }
export function Textarea({ label, hint, className = '', ...rest }: TextareaProps) {
  return (
    <Field label={label} hint={hint} className={className}>
      {(id, hintId) => <textarea id={id} {...rest} aria-describedby={describedBy(hintId, rest['aria-describedby'])} className={`${control} min-h-24 resize-y`} />}
    </Field>
  )
}

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & { label: string; hint?: ReactNode }
export function Select({ label, hint, className = '', children, ...rest }: SelectProps) {
  return (
    <Field label={label} hint={hint} className={className}>
      {(id, hintId) => (
        // appearance-none drops the browser's arrow, so draw one: without it a
        // dropdown reads as a box to type in.
        <div className="relative">
          <select id={id} {...rest} aria-describedby={describedBy(hintId, rest['aria-describedby'])} className={`${control} appearance-none pr-10`}>
            {children}
          </select>
          <ChevronDownIcon
            aria-hidden="true"
            className="pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
          />
        </div>
      )}
    </Field>
  )
}

export function Notice({ kind, children }: { kind: 'error' | 'success' | 'info'; children: ReactNode }) {
  if (!children) return null
  const tone =
    kind === 'error'
      ? 'bg-danger/10 text-danger border-danger/25'
      : kind === 'success'
        ? 'bg-success/10 text-success border-success/25'
        : 'bg-surface-2 text-muted border-line-strong'
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={`rounded-xl border px-3.5 py-2.5 text-sm ${tone}`}>
      {children}
    </div>
  )
}
