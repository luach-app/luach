import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AcceptInvite } from '../AcceptInvite'
import { Bootstrap } from '../Bootstrap'
import { Login } from '../Login'
import { Reset } from '../Reset'
import * as api from '../../../lib/api'
import { member } from '../../../test/harness'

describe('signing in', () => {
  it('takes a username and a password', async () => {
    const login = vi.spyOn(api.auth, 'login').mockResolvedValue(member as never)
    const onSignedIn = vi.fn()
    render(<Login onSignedIn={onSignedIn} />)
    await userEvent.type(screen.getByLabelText(/Username or email/i), 'robin')
    await userEvent.type(screen.getByLabelText(/^Password/i), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: /Sign in/i }))
    await waitFor(() => expect(login).toHaveBeenCalledWith('robin', 'correct horse battery'))
    expect(onSignedIn).toHaveBeenCalledWith(member)
  })

  it('says what the server said when it refuses', async () => {
    vi.spyOn(api.auth, 'login').mockRejectedValue(new api.ApiError(401, 'that username and password do not match'))
    render(<Login onSignedIn={() => {}} />)
    await userEvent.type(screen.getByLabelText(/Username or email/i), 'robin')
    await userEvent.type(screen.getByLabelText(/^Password/i), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: /Sign in/i }))
    await waitFor(() => expect(screen.getByText(/do not match/)).toBeInTheDocument())
  })

  it('offers the household’s single sign-on when the box has it, under its own label', () => {
    render(<Login onSignedIn={() => {}} sso={{ enabled: true, label: 'Sign in with Rivera' } as never} />)
    expect(screen.getByText('Sign in with Rivera')).toBeInTheDocument()
  })

  it('names single sign-on plainly when the server sends no label', () => {
    render(<Login onSignedIn={() => {}} sso={{ enabled: true, label: '' } as never} />)
    expect(screen.getByText('Sign in with single sign-on')).toBeInTheDocument()
  })

  it('names the household the server names, and none when it has no name', () => {
    const { unmount } = render(<Login onSignedIn={() => {}} household="Rivera" />)
    expect(screen.getByText('The Rivera household calendar.')).toBeInTheDocument()
    unmount()
    render(<Login onSignedIn={() => {}} household="" />)
    expect(screen.getByText('The household calendar.')).toBeInTheDocument()
  })

  it('can ask for a way back in', async () => {
    const forgot = vi.spyOn(api.auth, 'forgot').mockResolvedValue({ ok: true } as never)
    render(<Login onSignedIn={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: /Forgot/i }))
    await userEvent.type(screen.getByLabelText(/email/i), 'robin@example.com')
    await userEvent.click(screen.getByRole('button', { name: /Send|Email me/i }))
    await waitFor(() => expect(forgot).toHaveBeenCalledWith('robin@example.com'))
  })
})

describe('a forgotten password on a luach without mail', () => {
  it('does not promise a link; it says how the person who runs luach resets it', async () => {
    const forgot = vi.spyOn(api.auth, 'forgot')
    render(<Login onSignedIn={() => {}} mail={{ enabled: false, limitation: 'This luach does not send email.', offline_reset: 'docker compose exec luach python -m luach.passwd <username>' }} />)
    await userEvent.click(screen.getByRole('button', { name: /Forgot/i }))
    expect(screen.getByText(/does not send email, so a reset link cannot reach you/)).toBeInTheDocument()
    expect(screen.getByText('docker compose exec luach python -m luach.passwd <username>')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Send the link/i })).not.toBeInTheDocument()
    expect(forgot).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /Back to sign in/i }))
    expect(screen.getByLabelText(/Username or email/i)).toBeInTheDocument()
  })

  it('shows what mail cannot do when it is on but limited', async () => {
    vi.spyOn(api.auth, 'forgot').mockResolvedValue({ ok: true } as never)
    const limitation = 'Using Resend’s shared sender, which only delivers to the Resend account owner.'
    render(<Login onSignedIn={() => {}} mail={{ enabled: true, limitation }} />)
    await userEvent.click(screen.getByRole('button', { name: /Forgot/i }))
    expect(screen.getByText(limitation)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/email/i), 'robin@example.com')
    await userEvent.click(screen.getByRole('button', { name: /Send the link/i }))
    await waitFor(() => expect(screen.getByText(/reset link is on its way/)).toBeInTheDocument())
    expect(screen.getByText(limitation)).toBeInTheDocument()
  })
})

describe('the first account', () => {
  it('creates the owner', async () => {
    const register = vi.spyOn(api.auth, 'register').mockResolvedValue(member as never)
    const onSignedIn = vi.fn()
    render(<Bootstrap onSignedIn={onSignedIn} />)
    await userEvent.type(screen.getByLabelText(/Setup code/i), ' ABCD-EFGH-JKLM ')
    await userEvent.type(screen.getByLabelText(/Username/i), 'robin')
    await userEvent.type(screen.getByLabelText(/Email/i), 'robin@example.com')
    await userEvent.type(screen.getByLabelText(/Password/i), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: /Create|Start/i }))
    await waitFor(() => expect(register).toHaveBeenCalled())
    expect(register.mock.calls[0]?.[0]).toMatchObject({ username: 'robin', setup_code: 'ABCD-EFGH-JKLM' })
    expect(onSignedIn).toHaveBeenCalledWith(member, true)
  })

  it('asks for the setup code, and says it is in the server’s log', async () => {
    const register = vi.spyOn(api.auth, 'register').mockResolvedValue(member as never)
    render(<Bootstrap onSignedIn={() => {}} />)
    const code = screen.getByLabelText(/Setup code/i)
    expect(code).toBeRequired()
    expect(screen.getByText('docker compose logs luach')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Username/i), 'robin')
    await userEvent.type(screen.getByLabelText(/Email/i), 'robin@example.com')
    await userEvent.type(screen.getByLabelText(/Password/i), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: /Create/i }))
    expect(register).not.toHaveBeenCalled()
  })

  it('shows the server’s refusal of a wrong code', async () => {
    vi.spyOn(api.auth, 'register').mockRejectedValue(new api.ApiError(403, 'that setup code is wrong; luach prints it to its log'))
    render(<Bootstrap onSignedIn={() => {}} />)
    await userEvent.type(screen.getByLabelText(/Setup code/i), 'nope')
    await userEvent.type(screen.getByLabelText(/Username/i), 'robin')
    await userEvent.type(screen.getByLabelText(/Email/i), 'robin@example.com')
    await userEvent.type(screen.getByLabelText(/Password/i), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: /Create/i }))
    await waitFor(() => expect(screen.getByText(/setup code is wrong/)).toBeInTheDocument())
  })
})

/** This device's zone, as Intl reports it (jsdom's is the test machine's). */
function deviceZone(zone: string) {
  const real = Intl.DateTimeFormat.prototype.resolvedOptions
  return vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockImplementation(function (this: Intl.DateTimeFormat) {
    return { ...real.call(this), timeZone: zone }
  })
}

describe('the zone a new account starts in', () => {
  it('is this device’s for the owner, shown, and changeable before it is sent', async () => {
    deviceZone('Europe/Madrid')
    const register = vi.spyOn(api.auth, 'register').mockResolvedValue(member as never)
    render(<Bootstrap onSignedIn={() => {}} />)
    const zone = screen.getByLabelText('Time zone') as HTMLSelectElement
    expect(zone.value).toBe('Europe/Madrid')
    await userEvent.type(screen.getByLabelText(/Setup code/i), 'ABCD-EFGH-JKLM')
    await userEvent.type(screen.getByLabelText(/Username/i), 'robin')
    await userEvent.type(screen.getByLabelText(/Email/i), 'robin@example.com')
    await userEvent.type(screen.getByLabelText(/Password/i), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: /Create/i }))
    await waitFor(() => expect(register).toHaveBeenCalledTimes(1))
    expect(register.mock.calls[0]?.[0].timezone).toBe('Europe/Madrid')
  })

  it('can be changed on the setup screen', async () => {
    deviceZone('UTC')
    const register = vi.spyOn(api.auth, 'register').mockResolvedValue(member as never)
    render(<Bootstrap onSignedIn={() => {}} />)
    await userEvent.selectOptions(screen.getByLabelText('Time zone'), 'Asia/Jerusalem')
    await userEvent.type(screen.getByLabelText(/Setup code/i), 'ABCD-EFGH-JKLM')
    await userEvent.type(screen.getByLabelText(/Username/i), 'robin')
    await userEvent.type(screen.getByLabelText(/Email/i), 'robin@example.com')
    await userEvent.type(screen.getByLabelText(/Password/i), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: /Create/i }))
    await waitFor(() => expect(register).toHaveBeenCalledTimes(1))
    expect(register.mock.calls[0]?.[0].timezone).toBe('Asia/Jerusalem')
  })

  it('is this device’s for an invited member too', async () => {
    deviceZone('America/Los_Angeles')
    vi.spyOn(api.auth, 'invite').mockResolvedValue({ email: 'ana@example.com', inviter: 'Robin', expires_at: '2026-09-19T00:00:00' } as never)
    const accept = vi.spyOn(api.auth, 'accept').mockResolvedValue(member as never)
    render(<AcceptInvite token="tok" onSignedIn={() => {}} onCancel={() => {}} />)
    await waitFor(() => expect(screen.getByText(/Robin/)).toBeInTheDocument())
    expect((screen.getByLabelText('Time zone') as HTMLSelectElement).value).toBe('America/Los_Angeles')
    await userEvent.type(screen.getByLabelText(/Username/i), 'ana')
    await userEvent.type(screen.getByLabelText(/Password/i), 'another good password')
    await userEvent.click(screen.getByRole('button', { name: /Create my account/i }))
    await waitFor(() => expect(accept).toHaveBeenCalledTimes(1))
    expect(accept.mock.calls[0]?.[0]).toMatchObject({ token: 'tok', username: 'ana', timezone: 'America/Los_Angeles' })
  })
})

describe('an invitation', () => {
  it('shows who invited whom, then takes a username and password', async () => {
    vi.spyOn(api.auth, 'invite').mockResolvedValue({ email: 'ana@example.com', inviter: 'Robin', expires_at: '2026-09-19T00:00:00' } as never)
    const accept = vi.spyOn(api.auth, 'accept').mockResolvedValue(member as never)
    render(<AcceptInvite token="tok" onSignedIn={() => {}} onCancel={() => {}} />)
    await waitFor(() => expect(screen.getByText(/Robin/)).toBeInTheDocument())
    await userEvent.type(screen.getByLabelText(/Username/i), 'ana')
    await userEvent.type(screen.getByLabelText(/Password/i), 'another good password')
    await userEvent.click(screen.getByRole('button', { name: /Join|Accept|Create/i }))
    await waitFor(() => expect(accept).toHaveBeenCalled())
  })

  it('says plainly when the link is spent', async () => {
    vi.spyOn(api.auth, 'invite').mockRejectedValue(new api.ApiError(404, 'this invitation is no longer valid'))
    render(<AcceptInvite token="old" onSignedIn={() => {}} onCancel={() => {}} />)
    await waitFor(() => expect(screen.getByText(/no longer valid/)).toBeInTheDocument())
  })
})

describe('a password reset', () => {
  it('sets a new one', async () => {
    const reset = vi.spyOn(api.auth, 'reset').mockResolvedValue(member as never)
    render(<Reset token="tok" onSignedIn={() => {}} onCancel={() => {}} />)
    await userEvent.type(screen.getByLabelText('New password'), 'a brand new one')
    await userEvent.type(screen.getByLabelText('Repeat it'), 'a brand new one')
    await userEvent.click(screen.getByRole('button', { name: 'Save and sign in' }))
    await waitFor(() => expect(reset).toHaveBeenCalledWith('tok', 'a brand new one'))
  })
})
