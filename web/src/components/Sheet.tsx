import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { CloseIcon } from './Icons'

interface Props {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  /** The house board speaks its own language; a sheet it opens follows it. */
  dir?: 'ltr' | 'rtl'
  lang?: string
  closeLabel?: string
}

/** Bottom sheet on phones, centred dialog on wide screens. */
export function Sheet({ open, title, onClose, children, footer, dir, lang, closeLabel = 'Close' }: Props) {
  const panel = useRef<HTMLDivElement>(null)
  const restore = useRef<HTMLElement | null>(null)
  // The newest onClose, read when it is needed. As a dependency of the effect below,
  // every parent render with an inline onClose re-ran it: on the wall board, whose
  // day reloads every 20 seconds, focus jumped back to the first field and the
  // on-screen keyboard closed while someone was typing.
  const close = useRef(onClose)
  useEffect(() => {
    close.current = onClose
  })

  useEffect(() => {
    if (!open) return
    restore.current = document.activeElement as HTMLElement | null
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const first = panel.current?.querySelector<HTMLElement>('input, textarea, select, button')
    first?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        close.current()
        return
      }
      if (e.key === 'Tab') trapTab(e, panel.current)
    }
    // Focus that lands outside the sheet (a click on the page behind, a script) is
    // brought back in: it is modal.
    const onFocus = (e: FocusEvent) => {
      const box = panel.current
      if (box && e.target instanceof Node && !box.contains(e.target)) focusables(box)[0]?.focus()
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('focusin', onFocus)
    return () => {
      document.body.style.overflow = prev
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('focusin', onFocus)
      restore.current?.focus?.()
    }
  }, [open])

  if (!open) return null
  return createPortal(
    <div className="fixed inset-x-0 top-0 z-50 flex h-dvh items-end justify-center md:items-center" dir={dir} lang={lang}>
      <button aria-label={closeLabel} tabIndex={-1} className="absolute inset-0 bg-black/55 backdrop-blur-[2px]" onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="sheet-up relative flex max-h-[92dvh] w-full flex-col rounded-t-3xl bg-surface shadow-[var(--shadow)] md:max-h-[85dvh] md:w-[min(560px,92vw)] md:rounded-3xl"
      >
        <div className="flex items-center justify-between px-5 pt-4 pb-2">
          <div className="mx-auto h-1.5 w-10 rounded-full bg-line-strong md:hidden absolute left-1/2 top-2 -translate-x-1/2" />
          <h2 className="mt-2 text-lg font-semibold md:mt-0">{title}</h2>
          <button
            aria-label={closeLabel}
            onClick={onClose}
            className="mt-2 rounded-full p-2 text-muted hover:bg-surface-2 hover:text-text md:mt-0"
          >
            <CloseIcon />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 pb-4">{children}</div>
        {footer ? (
          <div className="safe-bottom border-t border-line px-5 pt-3 pb-3">
            <div className="flex flex-wrap gap-2 justify-end">{footer}</div>
          </div>
        ) : (
          <div className="safe-bottom" />
        )}
      </div>
    </div>,
    document.body,
  )
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function focusables(box: HTMLElement): HTMLElement[] {
  return Array.from(box.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.tabIndex >= 0 && !el.closest('fieldset:disabled'))
}

/** Tab past the last control comes back to the first, and Shift+Tab the other way. */
function trapTab(e: KeyboardEvent, box: HTMLElement | null) {
  if (!box) return
  const items = focusables(box)
  if (!items.length) {
    e.preventDefault()
    return
  }
  const first = items[0]!
  const last = items[items.length - 1]!
  const at = document.activeElement
  if (e.shiftKey && (at === first || !box.contains(at))) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && (at === last || !box.contains(at))) {
    e.preventDefault()
    first.focus()
  }
}
