import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { dropTargetOf, type DragItem, type DropTarget } from './board'

/** How long a finger rests on something before it lifts. */
export const LIFT_MS = 450
/** How far it may wander before then and still be a press, not a scroll or a swipe. */
export const SLOP_PX = 8
/** The click a hold ends with comes at once, if at all; nothing later is swallowed. */
const SWALLOW_MS = 600

export interface Dragging {
  item: DragItem
  x: number
  y: number
  over: DropTarget | null
}

interface Press {
  id: number
  x: number
  y: number
  item: DragItem
  el: Element
  refuse: boolean
  lifted: boolean
  timer: ReturnType<typeof setTimeout> | undefined
}

interface Handlers {
  /** It lifted. */
  onLift: (item: DragItem) => void
  /** A long press on something that may not move. */
  onRefuse: (item: DragItem) => void
  /** Let go: over a target, or over nothing (null). */
  onDrop: (item: DragItem, over: DropTarget | null) => void
}

const under = (x: number, y: number): DropTarget | null =>
  // jsdom, and nothing else, has no elementFromPoint.
  typeof document.elementFromPoint === 'function' ? dropTargetOf(document.elementFromPoint(x, y)) : null

/**
 * Hold and drag, by pointer events: a long press lifts a card, the card follows the
 * finger, and letting go puts it down on whatever is under it. Not HTML5
 * drag-and-drop, which a touch screen never starts. A quick tap is still a tap,
 * and a finger that moves before the hold is up is scrolling or swiping, and is
 * left alone.
 */
export function useBoardDrag(enabled: boolean, handlers: Handlers) {
  const [dragging, setDragging] = useState<Dragging | null>(null)
  const press = useRef<Press | null>(null)
  const swallowUntil = useRef(0)
  const on = useRef(handlers)
  useEffect(() => {
    on.current = handlers
  })

  const listeners = useRef<(() => void) | null>(null)
  const end = useCallback(() => {
    const p = press.current
    if (p?.timer) clearTimeout(p.timer)
    press.current = null
    listeners.current?.()
    listeners.current = null
    setDragging(null)
  }, [])
  useEffect(() => end, [end])
  useEffect(() => {
    if (!enabled) end()
  }, [enabled, end])

  const lift = (p: Press) => {
    p.timer = undefined
    if (p.refuse) {
      swallowUntil.current = Date.now() + SWALLOW_MS
      end()
      on.current.onRefuse(p.item)
      return
    }
    p.lifted = true
    try {
      p.el.setPointerCapture?.(p.id)
    } catch {
      /* the pointer is already gone; the window still hears it */
    }
    try {
      navigator.vibrate?.(10)
    } catch {
      /* no buzz on this screen */
    }
    setDragging({ item: p.item, x: p.x, y: p.y, over: null })
    on.current.onLift(p.item)
  }

  const start = (e: ReactPointerEvent, item: DragItem, refuse: boolean) => {
    if (!enabled || press.current) return
    if (e.pointerType === 'mouse' && e.button !== 0) return
    const p: Press = { id: e.pointerId, x: e.clientX, y: e.clientY, item, el: e.currentTarget, refuse, lifted: false, timer: undefined }
    press.current = p
    p.timer = setTimeout(() => lift(p), LIFT_MS)

    const move = (ev: PointerEvent) => {
      if (ev.pointerId !== p.id) return
      if (!p.lifted) {
        if (Math.hypot(ev.clientX - p.x, ev.clientY - p.y) > SLOP_PX) end()
        return
      }
      ev.preventDefault()
      const over = under(ev.clientX, ev.clientY)
      setDragging({ item: p.item, x: ev.clientX, y: ev.clientY, over })
    }
    const up = (ev: PointerEvent) => {
      if (ev.pointerId !== p.id) return
      const lifted = p.lifted
      end()
      if (!lifted) return
      swallowUntil.current = Date.now() + SWALLOW_MS
      on.current.onDrop(p.item, under(ev.clientX, ev.clientY))
    }
    const cancel = (ev: PointerEvent) => {
      if (ev.pointerId !== p.id) return
      const lifted = p.lifted
      end()
      if (lifted) on.current.onDrop(p.item, null)
    }
    const key = (ev: KeyboardEvent) => {
      if (ev.key !== 'Escape' || !p.lifted) return
      end()
      on.current.onDrop(p.item, null)
    }
    // Once something is lifted the page must not scroll under it. Only a
    // non-passive touchmove can stop that, and React's are passive.
    const still = (ev: TouchEvent) => {
      if (p.lifted && ev.cancelable) ev.preventDefault()
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', cancel)
    window.addEventListener('keydown', key)
    document.addEventListener('touchmove', still, { passive: false })
    listeners.current = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', cancel)
      window.removeEventListener('keydown', key)
      document.removeEventListener('touchmove', still)
    }
  }

  /** Spread on a card that can be held. `refuse`: it may not move, and a hold says why. */
  const holdable = (item: DragItem, refuse = false) =>
    enabled
      ? {
          onPointerDown: (e: ReactPointerEvent) => start(e, item, refuse),
          // A long press on a phone otherwise opens the browser's own menu.
          onContextMenu: (e: { preventDefault: () => void }) => e.preventDefault(),
          style: { WebkitTouchCallout: 'none' as const, touchAction: 'manipulation' as const },
        }
      : {}

  /** On the board's root, in the capture phase: the click a hold ends with is not a tap. */
  const onClickCapture = (e: { preventDefault: () => void; stopPropagation: () => void }) => {
    if (Date.now() >= swallowUntil.current) return
    swallowUntil.current = 0
    e.preventDefault()
    e.stopPropagation()
  }
  /** A new touch is a new gesture: its click is its own. */
  const onPointerDownCapture = () => {
    swallowUntil.current = 0
  }

  return { dragging, holdable, onClickCapture, onPointerDownCapture, isDragging: () => !!press.current?.lifted }
}
