import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Sheet } from '../Sheet'

/** A parent that re-renders on its own, as the wall board does every 20 seconds,
 * and hands the sheet a new inline onClose each time. */
function Reloading({ onClose }: { onClose: (n: number) => void }) {
  const [n, setN] = useState(0)
  return (
    <>
      <button onClick={() => setN((x) => x + 1)}>reload {n}</button>
      <Sheet open title="New event" onClose={() => onClose(n)} footer={<button>Save</button>}>
        <input aria-label="Title" />
        <input aria-label="Location" />
      </Sheet>
    </>
  )
}

describe('a sheet', () => {
  it('keeps focus where it is when the page behind it re-renders', async () => {
    const reload = { click: () => {} }
    render(<Reloading onClose={() => {}} />)
    // Opening puts focus in the sheet (its first control, the close button).
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true)
    await userEvent.click(screen.getByLabelText('Location'))
    await userEvent.keyboard('Park')
    // The board's reload: a parent render, not a click inside the sheet.
    reload.click = () => screen.getByText(/^reload/).click()
    act(() => reload.click())
    act(() => reload.click())
    expect(screen.getByText('reload 2')).toBeInTheDocument()
    expect(screen.getByLabelText('Location')).toHaveFocus()
  })

  it('closes on Escape with the newest onClose', async () => {
    const onClose = vi.fn()
    render(<Reloading onClose={onClose} />)
    act(() => screen.getByText(/^reload/).click())
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledWith(1)
  })

  it('keeps Tab inside: past the last control back to the first, and back again', async () => {
    render(<Reloading onClose={() => {}} />)
    const title = screen.getByLabelText('Title')
    const save = screen.getByRole('button', { name: 'Save' })
    save.focus()
    await userEvent.tab()
    // The first control in the dialog is its close button.
    expect(screen.getAllByRole('button', { name: 'Close' }).at(-1)).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(save).toHaveFocus()
    title.focus()
    await userEvent.tab()
    expect(screen.getByLabelText('Location')).toHaveFocus()
    // Nothing behind the sheet can be reached: the page's own button is skipped.
    for (let i = 0; i < 5; i++) await userEvent.tab()
    expect(screen.getByText(/^reload/)).not.toHaveFocus()
  })

  it('brings focus back in when it lands behind it', () => {
    render(<Reloading onClose={() => {}} />)
    act(() => screen.getByText(/^reload/).focus())
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true)
  })
})
