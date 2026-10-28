import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Mailbox } from '../Mailbox'
import { CHANNEL, finishConsentPopup, resultOf } from '../../lib/mailPopup'
import * as api from '../../lib/api'

const off = { connected: false, address: '', via: '' as const, can_connect: true }

describe('your email', () => {
  it('offers to connect your own Gmail when it is not connected', async () => {
    vi.spyOn(api.mail, 'status').mockResolvedValue(off)
    render(<Mailbox />)
    expect(await screen.findByRole('button', { name: 'Connect my Gmail' })).toBeInTheDocument()
    expect(screen.getByText(/only\s+your own mailbox/)).toBeInTheDocument()
  })

  it('shows the connected address and disconnects', async () => {
    vi.spyOn(api.mail, 'status').mockResolvedValue({ connected: true, address: 'me@gmail.com', via: 'own', can_connect: true })
    const disconnect = vi.spyOn(api.mail, 'disconnect').mockResolvedValue({ ok: true, ...off })
    render(<Mailbox />)
    expect(await screen.findByText('me@gmail.com')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Disconnect' }))
    await waitFor(() => expect(disconnect).toHaveBeenCalled())
    expect(await screen.findByRole('button', { name: 'Connect my Gmail' })).toBeInTheDocument()
  })

  it('turns on reading new mail, and says nothing is added without a yes', async () => {
    const scan = { available: true, enabled: false, since: '', minutes: 10 }
    const connected = { connected: true, address: 'me@gmail.com', via: 'own' as const, can_connect: true, scan }
    vi.spyOn(api.mail, 'status').mockResolvedValue(connected)
    const set = vi.spyOn(api.mail, 'scan').mockResolvedValue({ ...connected, scan: { ...scan, enabled: true, since: '2026-09-30T12:00:00' } })
    render(<Mailbox />)
    const box = await screen.findByRole('checkbox', { name: /Look through new mail/ })
    expect(box).not.toBeChecked()
    expect(screen.getByText(/Nothing is added until you say yes, and only you see what it found/)).toBeInTheDocument()
    await userEvent.click(box)
    await waitFor(() => expect(set).toHaveBeenCalledWith(true))
    expect(await screen.findByRole('checkbox', { name: /Look through new mail/ })).toBeChecked()
  })

  it('offers no scan where the mailbox is not connected or the scan is off here', async () => {
    const scan = { available: true, enabled: false, since: '', minutes: 10 }
    vi.spyOn(api.mail, 'status').mockResolvedValue({ ...off, scan })
    const { unmount } = render(<Mailbox />)
    await screen.findByRole('button', { name: 'Connect my Gmail' })
    expect(screen.queryByRole('checkbox')).toBeNull()
    unmount()
    vi.spyOn(api.mail, 'status').mockResolvedValue({ connected: true, address: 'a@b.c', via: 'own', can_connect: true, scan: { ...scan, available: false } })
    render(<Mailbox />)
    await screen.findByText('a@b.c')
    expect(screen.queryByRole('checkbox')).toBeNull()
  })

  it('opens Google in a popup, and shows connected when the popup says so', async () => {
    const status = vi.spyOn(api.mail, 'status').mockResolvedValue(off)
    const open = vi.spyOn(window, 'open').mockReturnValue({} as Window)
    render(<Mailbox />)
    await userEvent.click(await screen.findByRole('button', { name: 'Connect my Gmail' }))
    expect(open).toHaveBeenCalledWith('/api/mail/connect?popup=1', 'luach-gmail', expect.stringContaining('popup'))

    status.mockResolvedValue({ connected: true, address: 'me@gmail.com', via: 'own', can_connect: true })
    const channel = new BroadcastChannel(CHANNEL)
    channel.postMessage({ mail: 'connected' })
    channel.close()
    expect(await screen.findByText('me@gmail.com')).toBeInTheDocument()
    expect(screen.getByText('Your email is connected.')).toBeInTheDocument()
  })

  it('goes to Google in the whole window when popups are blocked', async () => {
    vi.spyOn(api.mail, 'status').mockResolvedValue(off)
    vi.spyOn(window, 'open').mockReturnValue(null)
    const assign = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, assign } as Location)
    render(<Mailbox />)
    await userEvent.click(await screen.findByRole('button', { name: 'Connect my Gmail' }))
    expect(assign).toHaveBeenCalledWith('/api/mail/connect')
  })

  it('the popup, back from Google, reports and closes; any other page loads the app', () => {
    const close = vi.spyOn(window, 'close').mockImplementation(() => {})
    const heard: unknown[] = []
    const channel = new BroadcastChannel(CHANNEL)
    channel.onmessage = (e) => heard.push(e.data)
    window.history.replaceState(null, '', '/?tab=settings&mail=connected&popup=1')
    expect(finishConsentPopup()).toBe(true)
    expect(close).toHaveBeenCalled()
    window.history.replaceState(null, '', '/?tab=settings&mail=connected')
    expect(finishConsentPopup()).toBe(false)
    window.history.replaceState(null, '', '/')
    return new Promise<void>((done, fail) =>
      setTimeout(() => {
        channel.close()
        try {
          expect(heard).toEqual([{ mail: 'connected' }])
          done()
        } catch (e) {
          fail(e)
        }
      }, 50),
    )
  })

  it('says so when the Gmail signed in to is not one of your addresses', async () => {
    expect(resultOf('?tab=settings&mail=failed&reason=not-yours')).toBe('not-yours')
    expect(resultOf('?tab=settings&mail=failed')).toBe('failed')
    expect(resultOf('?tab=settings&mail=connected')).toBe('connected')
    expect(resultOf('?tab=settings')).toBeNull()

    vi.spyOn(api.mail, 'status').mockResolvedValue(off)
    vi.spyOn(window, 'open').mockReturnValue({} as Window)
    render(<Mailbox />)
    await userEvent.click(await screen.findByRole('button', { name: 'Connect my Gmail' }))
    const channel = new BroadcastChannel(CHANNEL)
    channel.postMessage({ mail: 'not-yours' })
    channel.close()
    expect(await screen.findByText(/That Gmail is not one of your addresses here/)).toBeInTheDocument()
  })

  it('a popup refused as not yours reports that, not a plain failure', () => {
    vi.spyOn(window, 'close').mockImplementation(() => {})
    const heard: unknown[] = []
    const channel = new BroadcastChannel(CHANNEL)
    channel.onmessage = (e) => heard.push(e.data)
    window.history.replaceState(null, '', '/?tab=settings&mail=failed&reason=not-yours&popup=1')
    expect(finishConsentPopup()).toBe(true)
    window.history.replaceState(null, '', '/')
    return new Promise<void>((done, fail) =>
      setTimeout(() => {
        channel.close()
        try {
          expect(heard).toEqual([{ mail: 'not-yours' }])
          done()
        } catch (e) {
          fail(e)
        }
      }, 50),
    )
  })

  it('names the household mailbox, and offers the owner their own connection instead', async () => {
    vi.spyOn(api.mail, 'status').mockResolvedValue({ connected: true, address: 'robin@example.com', via: 'household', can_connect: true })
    const open = vi.spyOn(window, 'open').mockReturnValue({} as Window)
    render(<Mailbox />)
    expect(await screen.findByText('robin@example.com')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Connect my own Gmail' }))
    expect(open).toHaveBeenCalledWith('/api/mail/connect?popup=1', 'luach-gmail', expect.any(String))
    expect(screen.queryByRole('button', { name: 'Disconnect' })).toBeNull()
  })

  it('does not offer a connect that is not set up here', async () => {
    vi.spyOn(api.mail, 'status').mockResolvedValue({ ...off, can_connect: false })
    render(<Mailbox />)
    expect(await screen.findByText(/not set up on this luach yet/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Connect my Gmail' })).toBeNull()
  })
})

describe('a Gmail Google took back', () => {
  const lost = { ...off, lost: { address: 'me@gmail.com', since: '2026-10-20T08:00:00', via: 'own' as const } }

  it('says it is disconnected and offers to reconnect', async () => {
    vi.spyOn(api.mail, 'status').mockResolvedValue(lost)
    const open = vi.spyOn(window, 'open').mockReturnValue({} as Window)
    render(<Mailbox />)
    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('Gmail disconnected — reconnect')
    expect(banner).toHaveTextContent('me@gmail.com')
    // One way to connect, not two.
    expect(screen.queryByRole('button', { name: 'Connect my Gmail' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Reconnect Gmail' }))
    expect(open).toHaveBeenCalledWith('/api/mail/connect?popup=1', 'luach-gmail', expect.stringContaining('popup'))
  })

  it('names the household mailbox when the door lost its grant, and can be dismissed', async () => {
    vi.spyOn(api.mail, 'status').mockResolvedValue({ ...lost, lost: { ...lost.lost, via: 'household' } })
    const dismiss = vi.spyOn(api.mail, 'disconnect').mockResolvedValue({ ok: true, ...off, lost: null })
    render(<Mailbox />)
    expect(await screen.findByRole('alert')).toHaveTextContent('household mailbox')
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    await waitFor(() => expect(dismiss).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).toBeNull()
    expect(await screen.findByRole('button', { name: 'Connect my Gmail' })).toBeInTheDocument()
  })
})
