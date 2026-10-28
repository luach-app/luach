interface Props {
  size?: 'sm' | 'md' | 'lg'
  className?: string
  /** Just the Hebrew mark — for a collapsed rail, where the word will not fit. */
  mark?: boolean
}

const sizes = {
  sm: { he: 'text-2xl', en: 'text-xs' },
  md: { he: 'text-4xl', en: 'text-sm' },
  lg: { he: 'text-6xl', en: 'text-base' },
}

/** Wordmark: the Hebrew word לוח, with "luach" small beside it. */
export function Logo({ size = 'md', className = '', mark = false }: Props) {
  const s = sizes[size]
  return (
    <div className={`flex items-baseline gap-2 select-none ${className}`} aria-label="luach">
      <span lang="he" dir="rtl" className={`wordmark ${s.he}`}>
        לוח
      </span>
      {mark ? null : <span className={`${s.en} tracking-[0.22em] uppercase text-muted`}>luach</span>}
    </div>
  )
}
