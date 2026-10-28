import type { SVGProps } from 'react'

type P = SVGProps<SVGSVGElement>
const base = (p: P) => ({
  width: 22,
  height: 22,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
  ...p,
})

export const CalendarIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="3" y="5" width="18" height="16" rx="3" />
    <path d="M3 10h18M8 3v4M16 3v4" />
  </svg>
)
export const ChatIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1.1-4.1A8 8 0 1 1 21 12Z" />
  </svg>
)
export const ShieldIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M12 3 5 6v5c0 4.5 3 8.4 7 9.6 4-1.2 7-5.1 7-9.6V6l-7-3Z" />
    <path d="M9.5 12.2l1.8 1.8 3.4-3.6" />
  </svg>
)
export const PeopleIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="9" cy="8" r="3.2" />
    <path d="M3.5 19a5.5 5.5 0 0 1 11 0M16 4.5a3.2 3.2 0 0 1 0 6.4M20.5 19a5.5 5.5 0 0 0-4-5.3" />
  </svg>
)
export const GearIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
  </svg>
)
export const PlusIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M12 5v14M5 12h14" />
  </svg>
)
export const SendIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M4 12 20 4l-4 16-4.5-6.5L4 12Z" />
    <path d="M11.5 13.5 20 4" />
  </svg>
)
export const MicIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  </svg>
)
export const StopIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor" stroke="none" />
  </svg>
)
export const CloseIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
)
export const CheckIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M5 12.5 9.5 17 19 7" />
  </svg>
)
export const BoardIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="3" y="4" width="18" height="14" rx="2" />
    <path d="M9 4v14M15 4v14M8 21h8" />
  </svg>
)
export const ListCheckIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M4 7l2 2 3-3M4 15l2 2 3-3M12 8h8M12 16h8" />
  </svg>
)
export const ExternalIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" />
  </svg>
)
export const PinIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M12 21s-6-5.3-6-10.5a6 6 0 0 1 12 0C18 15.7 12 21 12 21Z" />
    <circle cx="12" cy="10.5" r="2.2" />
  </svg>
)
export const CopyIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M5 15V5a1 1 0 0 1 1-1h10" />
  </svg>
)
export const ChevronDownIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="m6 9 6 6 6-6" />
  </svg>
)
export const SearchIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
)
export const SparkIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" />
  </svg>
)
export const RepeatIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M17 2l4 4-4 4" />
    <path d="M3 11V9a4 4 0 0 1 4-4h14M7 22l-4-4 4-4" />
    <path d="M21 13v2a4 4 0 0 1-4 4H3" />
  </svg>
)
export const KeyIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="8" cy="14" r="4.5" />
    <path d="M11.5 11.5 20 3M16 7l2.5 2.5M13.5 9.5 16 12" />
  </svg>
)

/** Corners pushing outward: give the calendar the whole screen. */
export const ExpandIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M9 3H3v6M15 3h6v6M9 21H3v-6M15 21h6v-6" />
  </svg>
)

/** Corners pulling inward: give the chrome back. */
export const ShrinkIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M3 9h6V3M21 9h-6V3M3 15h6v6M21 15h-6v6" />
  </svg>
)

export const HistoryIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M3.5 9a9 9 0 1 0 2.6-4.3L3 8" />
    <path d="M3 3v5h5M12 7v5l3.5 2" />
  </svg>
)

export const TrashIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M4 7h16M10 11v6M14 11v6" />
    <path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
  </svg>
)

export const PencilIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4Z" />
    <path d="M14 6l4 4" />
  </svg>
)

/** An open book: a guide the assistant read before acting. */
export const BookIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M12 6.5C10.5 5.2 8.3 4.5 5.5 4.5H3v13h2.5c2.8 0 5 .7 6.5 2 1.5-1.3 3.7-2 6.5-2H21v-13h-2.5c-2.8 0-5 .7-6.5 2Z" />
    <path d="M12 6.5v13" />
  </svg>
)
