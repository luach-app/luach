import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { notesAsText, renderNotes } from '../notes'

const GOOGLE =
  '<b>Join Google Meet:</b> <a href="https://meet.google.com/jdv-ivfc-xhb">https://meet.google.com/jdv-ivfc-xhb</a><br/><br/><p>Agenda:</p><ul><li><p>10:00 AM - 11:00 AM (EDT) - System Design Interview</p></li><li><p>11:00 AM - 12:00 PM (EDT) - Coding Interview</p></li></ul>'

describe("an event's notes", () => {
  it("shows Google's HTML as formatting, not as markup", () => {
    const { container } = render(<div>{renderNotes(GOOGLE)}</div>)
    expect(container.textContent).not.toContain('<b>')
    expect(screen.getByText('Join Google Meet:').tagName).toBe('STRONG')
    const link = screen.getByRole('link', { name: 'https://meet.google.com/jdv-ivfc-xhb' })
    expect(link).toHaveAttribute('href', 'https://meet.google.com/jdv-ivfc-xhb')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('carries no script, handler or javascript: link into the page', () => {
    const evil = '<p onclick="alert(1)">hi</p><script>alert(2)</script><a href="javascript:alert(3)">click</a><img src=x onerror="alert(4)">'
    const { container } = render(<div>{renderNotes(evil)}</div>)
    expect(container.querySelector('script, img, [onclick]')).toBeNull()
    expect(container.querySelector('a')).toBeNull()
    expect(container.textContent).toContain('click')
  })

  it('makes the links in plain notes clickable', () => {
    render(<div>{renderNotes('Zoom: https://zoom.us/j/123 see you')}</div>)
    expect(screen.getByRole('link', { name: 'https://zoom.us/j/123' })).toHaveAttribute('href', 'https://zoom.us/j/123')
  })

  it('turns HTML into lines a person can edit', () => {
    const text = notesAsText(GOOGLE)
    expect(text).not.toMatch(/<[a-z]/i)
    expect(text).toContain('Join Google Meet: https://meet.google.com/jdv-ivfc-xhb')
    expect(text).toContain('• 10:00 AM - 11:00 AM (EDT) - System Design Interview')
    expect(notesAsText('plain words')).toBe('plain words')
  })
})
