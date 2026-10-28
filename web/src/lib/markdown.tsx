import { Fragment, type ReactNode } from 'react'

/**
 * Lightweight, allocation-only markdown for assistant prose: **bold**, *italic*,
 * `code`, bare URLs, "- " / "• " / "1. " lists, "#" headings, blank-line paragraphs.
 * Builds React nodes — model text never reaches innerHTML.
 */
export function renderMarkdown(text: string): ReactNode {
  const blocks = splitBlocks(text)
  return blocks.map((b, i) => {
    if (b.kind === 'list') {
      const Tag = b.ordered ? 'ol' : 'ul'
      return (
        <Tag key={i} className={`my-1.5 flex flex-col gap-1 ps-5 ${b.ordered ? 'list-decimal' : 'list-disc'} marker:text-muted`}>
          {b.items.map((item, j) => (
            <li key={j} dir="auto">
              {inline(item)}
            </li>
          ))}
        </Tag>
      )
    }
    if (b.kind === 'heading') {
      return (
        <p key={i} className="mt-2 font-semibold first:mt-0" dir="auto">
          {inline(b.text)}
        </p>
      )
    }
    return (
      <p key={i} className="whitespace-pre-wrap [&+p]:mt-2" dir="auto">
        {inline(b.text)}
      </p>
    )
  })
}

type Block = { kind: 'para' | 'heading'; text: string } | { kind: 'list'; ordered: boolean; items: string[] }

const BULLET = /^\s*(?:[-•*]|(\d+)[.)])\s+(.*)$/
const HEADING = /^\s*#{1,6}\s+(.*)$/

function splitBlocks(text: string): Block[] {
  const blocks: Block[] = []
  let para: string[] = []
  const flush = () => {
    if (para.length) blocks.push({ kind: 'para', text: para.join('\n') })
    para = []
  }
  for (const raw of text.replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trimEnd()
    if (!line.trim()) {
      flush()
      continue
    }
    const h = HEADING.exec(line)
    if (h) {
      flush()
      blocks.push({ kind: 'heading', text: h[1] ?? '' })
      continue
    }
    const m = BULLET.exec(line)
    if (m) {
      flush()
      const ordered = m[1] !== undefined
      const last = blocks[blocks.length - 1]
      if (last && last.kind === 'list' && last.ordered === ordered) last.items.push(m[2] ?? '')
      else blocks.push({ kind: 'list', ordered, items: [m[2] ?? ''] })
      continue
    }
    para.push(line)
  }
  flush()
  return blocks
}

const INLINE = /(\*\*[^*\n]+?\*\*|`[^`\n]+`|(?<![\w*])\*[^*\n]+?\*(?![\w*])|https?:\/\/[^\s<>"')\]]+)/g

function inline(text: string): ReactNode {
  const parts = text.split(INLINE)
  if (parts.length === 1) return text
  return parts.map((p, i) => {
    if (i % 2 === 0) return p ? <Fragment key={i}>{p}</Fragment> : null
    if (p.startsWith('**')) return <strong key={i}>{p.slice(2, -2)}</strong>
    if (p.startsWith('`')) return <code key={i} className="rounded bg-surface-2 px-1 text-[0.9em]">{p.slice(1, -1)}</code>
    if (p.startsWith('*')) return <em key={i}>{p.slice(1, -1)}</em>
    const m = /^(.*?)([.,;:!?]*)$/.exec(p)
    const href = m?.[1] ?? p
    const tail = m?.[2] ?? ''
    return (
      <Fragment key={i}>
        <a href={href} target="_blank" rel="noreferrer noopener" className="break-all text-accent-text underline decoration-accent/40 underline-offset-2 hover:decoration-accent">
          {href}
        </a>
        {tail}
      </Fragment>
    )
  })
}
