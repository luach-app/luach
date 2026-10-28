import type { ReactNode } from 'react'

/**
 * An event's notes, as a person should read them. Google stores an invitation's
 * description as HTML ("<b>Join Google Meet:</b> <a href=…>…</a><br/><p>Agenda:</p><ul>…"),
 * and the sheet printed it as markup. This keeps the few elements notes are made of and
 * drops everything else; nothing is ever set as raw HTML, so a description can carry no
 * script, style or handler into the page.
 */
const LOOKS_LIKE_HTML = /<\/?(a|b|strong|i|em|u|br|p|div|span|ul|ol|li|h[1-6])\b[^>]*>/i
const URL = /(https?:\/\/[^\s<>"')]+)/g
const SAFE_HREF = /^(https?:|mailto:)/i

function linkify(text: string, key: string): ReactNode[] {
  return text.split(URL).map((part, i) =>
    i % 2 === 1 ? (
      <a key={`${key}-${i}`} href={part} target="_blank" rel="noopener noreferrer" className="text-accent-text underline underline-offset-2 break-all">
        {part}
      </a>
    ) : (
      part
    ),
  )
}

function walk(node: Node, key: string, inLink = false): ReactNode {
  // A link's own words are not linked again: that nested one link inside another.
  if (node.nodeType === Node.TEXT_NODE) return inLink ? node.textContent : linkify(node.textContent ?? '', key)
  if (node.nodeType !== Node.ELEMENT_NODE) return null
  const el = node as Element
  const isLink = el.tagName.toLowerCase() === 'a'
  const kids = Array.from(el.childNodes).map((c, i) => walk(c, `${key}.${i}`, inLink || isLink))
  switch (el.tagName.toLowerCase()) {
    case 'b':
    case 'strong':
      return <strong key={key}>{kids}</strong>
    case 'i':
    case 'em':
      return <em key={key}>{kids}</em>
    case 'u':
      return <u key={key}>{kids}</u>
    case 'br':
      return <br key={key} />
    case 'p':
    case 'div':
      return (
        <p key={key} className="my-1">
          {kids}
        </p>
      )
    case 'ul':
      return (
        <ul key={key} className="my-1 list-disc ps-5">
          {kids}
        </ul>
      )
    case 'ol':
      return (
        <ol key={key} className="my-1 list-decimal ps-5">
          {kids}
        </ol>
      )
    case 'li':
      return <li key={key}>{kids}</li>
    case 'a': {
      const href = el.getAttribute('href') ?? ''
      if (!SAFE_HREF.test(href)) return <span key={key}>{kids}</span>
      return (
        <a key={key} href={href} target="_blank" rel="noopener noreferrer" className="text-accent-text underline underline-offset-2 break-all">
          {kids}
        </a>
      )
    }
    case 'script':
    case 'style':
    case 'iframe':
    case 'object':
      return null
    default:
      return <span key={key}>{kids}</span>
  }
}

export function isHtmlNotes(text: string): boolean {
  return LOOKS_LIKE_HTML.test(text)
}

/** Notes for reading: HTML made safe, plain text with its links made clickable. */
export function renderNotes(text: string): ReactNode {
  if (!isHtmlNotes(text)) return linkify(text, 'n')
  const doc = new DOMParser().parseFromString(`<div>${text}</div>`, 'text/html')
  const root = doc.body.firstElementChild
  return root ? Array.from(root.childNodes).map((c, i) => walk(c, `n${i}`)) : text
}

/**
 * Notes for editing, as text: an HTML description becomes lines a person can edit,
 * with each link's address kept beside its words.
 */
export function notesAsText(text: string): string {
  if (!isHtmlNotes(text)) return text
  const doc = new DOMParser().parseFromString(`<div>${text}</div>`, 'text/html')
  const root = doc.body.firstElementChild
  if (!root) return text
  const out: string[] = []
  const visit = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      out.push(node.textContent ?? '')
      return
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return
    const el = node as Element
    const tag = el.tagName.toLowerCase()
    if (tag === 'script' || tag === 'style') return
    if (tag === 'br') {
      out.push('\n')
      return
    }
    if (tag === 'li') out.push('\n• ')
    el.childNodes.forEach(visit)
    if (tag === 'a') {
      const href = el.getAttribute('href') ?? ''
      if (SAFE_HREF.test(href) && !(el.textContent ?? '').includes(href)) out.push(` (${href})`)
    }
    if (tag === 'p' || tag === 'div' || tag === 'ul' || tag === 'ol') out.push('\n')
  }
  root.childNodes.forEach(visit)
  return out
    .join('')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
