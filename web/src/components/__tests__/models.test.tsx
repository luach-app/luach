import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Models } from '../Models'
import * as api from '../../lib/api'
import { contextLabel, moved, priceLabel, verdictLabel, type ManagedModel, type ModelsSnapshot, type ModelTrial } from '../../lib/models'

const ok = { status: 'ok' as const, since: null, reason: '' }

function model(over: Partial<ManagedModel> = {}): ManagedModel {
  return {
    id: 'qwen-home',
    name: 'At home',
    about: 'Runs here.',
    local: true,
    provider: '',
    provider_set: '',
    enabled: true,
    position: 0,
    is_default: true,
    meta: {},
    failures: 0,
    last_ok_at: null,
    health: ok,
    trial: null,
    ...over,
  }
}

const cloud = model({
  id: 'openrouter/deepseek/flash',
  name: 'DeepSeek',
  about: 'Fast.',
  local: false,
  provider: 'DeepSeek, through OpenRouter',
  is_default: false,
  position: 1,
  trial: { passed: 12, total: 12, verdict: 'good', at: '2026-10-28T12:00:00Z' },
})

function snap(over: Partial<ModelsSnapshot> = {}): ModelsSnapshot {
  return {
    default: 'qwen-home',
    configured: true,
    models: [model(), cloud],
    trial: null,
    trials_left_today: 6,
    catalogue: { configured: true, source: 'openrouter.ai' },
    ...over,
  }
}

function trial(over: Partial<ModelTrial> = {}): ModelTrial {
  return {
    id: 1,
    model: 'openrouter/deepseek/flash',
    status: 'running',
    requested_by: 'robin',
    started_at: '2026-10-28T12:00:00Z',
    finished_at: null,
    done: 3,
    passed: 3,
    total: 12,
    verdict: null,
    cases: [],
    error: '',
    ...over,
  }
}

beforeEach(() => {
  vi.spyOn(api.models, 'manage').mockResolvedValue(snap())
})
afterEach(() => {
  vi.useRealTimers()
})

const row = (name: string) => screen.getByRole('listitem', { name })

describe('the owner manages the model menu', () => {
  it('lists every model with where it runs, its score and whether it is the default', async () => {
    render(<Models />)
    await waitFor(() => expect(row('DeepSeek')).toBeInTheDocument())
    const home = row('At home')
    expect(within(home).getByText('Default')).toBeInTheDocument()
    expect(within(home).getByText('At home', { selector: 'span.rounded-full' })).toBeInTheDocument()
    expect(within(home).getByText('Not tried')).toBeInTheDocument()
    // The default stays on the menu and on the list.
    expect(within(home).getByRole('checkbox', { name: "At home on the members' menu" })).toBeDisabled()
    expect(within(home).queryByRole('button', { name: 'Remove At home' })).not.toBeInTheDocument()
    const deep = row('DeepSeek')
    expect(within(deep).getByText('DeepSeek, through OpenRouter')).toBeInTheDocument()
    expect(within(deep).getByText('Passed 12/12')).toBeInTheDocument()
    expect(screen.getByText('6 trials left today.')).toBeInTheDocument()
  })

  it('says when no model is set up', async () => {
    vi.mocked(api.models.manage).mockResolvedValue(snap({ configured: false, models: [], default: '' }))
    render(<Models />)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No model is set up yet'))
    expect(screen.getByText('No models yet.')).toBeInTheDocument()
  })

  it('shows a model that stopped answering, and why, and will not make it the default', async () => {
    vi.mocked(api.models.manage).mockResolvedValue(
      snap({ models: [model(), { ...cloud, health: { status: 'not_answering', since: '2026-10-28T12:00:00Z', reason: '404: No endpoints found' } }] }),
    )
    render(<Models />)
    await waitFor(() => expect(within(row('DeepSeek')).getByText('Not answering')).toBeInTheDocument())
    expect(within(row('DeepSeek')).getByText(/404: No endpoints found/)).toBeInTheDocument()
    expect(within(row('DeepSeek')).getByRole('button', { name: 'Make default' })).toBeDisabled()
  })

  it('warns plainly about a low score', async () => {
    vi.mocked(api.models.manage).mockResolvedValue(
      snap({ models: [model(), { ...cloud, trial: { passed: 6, total: 12, verdict: 'low', at: null } }] }),
    )
    render(<Models />)
    await waitFor(() => expect(within(row('DeepSeek')).getByText('Low score 6/12')).toBeInTheDocument())
    expect(within(row('DeepSeek')).getByRole('note')).toHaveTextContent('wrong thing to do in 6 of 12 cases')
  })

  it('turns a model on and off, makes it the default, moves it and removes it', async () => {
    const edit = vi.spyOn(api.models, 'edit').mockResolvedValue(snap({ models: [model(), { ...cloud, enabled: false }] }))
    const setDefault = vi.spyOn(api.models, 'setDefault').mockResolvedValue(snap())
    const order = vi.spyOn(api.models, 'order').mockResolvedValue(snap({ models: [{ ...cloud, position: 0 }, { ...model(), position: 1 }] }))
    const remove = vi.spyOn(api.models, 'remove').mockResolvedValue(snap({ models: [model()] }))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<Models />)
    await waitFor(() => expect(row('DeepSeek')).toBeInTheDocument())
    await userEvent.click(within(row('DeepSeek')).getByRole('checkbox'))
    expect(edit).toHaveBeenCalledWith({ id: cloud.id, enabled: false })
    await waitFor(() => expect(within(row('DeepSeek')).getByRole('checkbox')).not.toBeChecked())
    await userEvent.click(within(row('DeepSeek')).getByRole('button', { name: 'Make default' }))
    expect(setDefault).toHaveBeenCalledWith(cloud.id)
    await userEvent.click(within(row('DeepSeek')).getByRole('button', { name: 'Move DeepSeek up' }))
    expect(order).toHaveBeenCalledWith([cloud.id, 'qwen-home'])
    await waitFor(() => expect(screen.getAllByRole('listitem')[0]).toHaveAccessibleName('DeepSeek'))
    await userEvent.click(within(row('DeepSeek')).getByRole('button', { name: 'Remove DeepSeek' }))
    expect(remove).toHaveBeenCalledWith(cloud.id)
    await waitFor(() => expect(screen.queryByRole('listitem', { name: 'DeepSeek' })).not.toBeInTheDocument())
  })

  it('does not remove without a yes', async () => {
    const remove = vi.spyOn(api.models, 'remove')
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<Models />)
    await waitFor(() => expect(row('DeepSeek')).toBeInTheDocument())
    await userEvent.click(within(row('DeepSeek')).getByRole('button', { name: 'Remove DeepSeek' }))
    expect(remove).not.toHaveBeenCalled()
  })

  it('edits a name, what it says about itself, and where it runs', async () => {
    const edit = vi.spyOn(api.models, 'edit').mockResolvedValue(snap({ models: [model(), { ...cloud, name: 'DeepSeek V4' }] }))
    render(<Models />)
    await waitFor(() => expect(row('DeepSeek')).toBeInTheDocument())
    await userEvent.click(within(row('DeepSeek')).getByRole('button', { name: 'Edit' }))
    const name = within(row('DeepSeek')).getByLabelText('Name')
    await userEvent.clear(name)
    await userEvent.type(name, 'DeepSeek V4')
    await userEvent.type(within(row('DeepSeek')).getByLabelText('Who runs it'), 'DeepSeek')
    await userEvent.click(within(row('DeepSeek')).getByRole('button', { name: 'Save' }))
    expect(edit).toHaveBeenCalledWith({ id: cloud.id, name: 'DeepSeek V4', about: 'Fast.', provider: 'DeepSeek', local: false })
    await waitFor(() => expect(row('DeepSeek V4')).toBeInTheDocument())
  })

  it('says what the server refused', async () => {
    vi.spyOn(api.models, 'setDefault').mockRejectedValue(new api.ApiError(400, 'that model is not answering: check it, or choose another'))
    render(<Models />)
    await waitFor(() => expect(row('DeepSeek')).toBeInTheDocument())
    await userEvent.click(within(row('DeepSeek')).getByRole('button', { name: 'Make default' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('that model is not answering'))
  })

  it('checks a model now', async () => {
    vi.spyOn(api.models, 'check').mockResolvedValue({ ok: false, reason: '404: gone', health: null, models: [model(), cloud] })
    render(<Models />)
    await waitFor(() => expect(row('DeepSeek')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Check DeepSeek' }))
    await waitFor(() => expect(screen.getByText('DeepSeek did not answer: 404: gone')).toBeInTheDocument())
  })

  it('cannot load, and tries again', async () => {
    vi.mocked(api.models.manage).mockRejectedValueOnce(new api.ApiError(500, 'luach hit a problem on the server.'))
    render(<Models />)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('luach hit a problem'))
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(row('DeepSeek')).toBeInTheDocument())
  })
})

describe('Try it', () => {
  it('starts a trial, shows its progress, and the score when it ends', async () => {
    const tryIt = vi.spyOn(api.models, 'tryIt').mockResolvedValue({ trial: trial({ done: 0, passed: 0 }), trials_left_today: 5 })
    const poll = vi.spyOn(api.models, 'trial').mockResolvedValue({ trial: trial({ done: 7, passed: 7 }), trials_left_today: 5 })
    render(<Models />)
    await waitFor(() => expect(row('DeepSeek')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Try DeepSeek' }))
    expect(tryIt).toHaveBeenCalledWith(cloud.id)
    await waitFor(() => expect(screen.getByText('Trying DeepSeek: 7 of 12 cases')).toBeInTheDocument())
    expect(screen.getByRole('progressbar', { name: 'Trial of DeepSeek' })).toHaveAttribute('value', '7')
    // Only one at a time.
    expect(screen.getByRole('button', { name: 'Try At home' })).toBeDisabled()
    const done = trial({
      status: 'done',
      done: 12,
      passed: 6,
      verdict: 'low',
      cases: [
        { case: 'correction', about: "an event, then 'no, thursday'", ok: false, problems: ['swim: 2 events, wanted 1'], tools: [] },
        { case: 'greeting', about: 'a greeting', ok: true, problems: [], tools: [] },
      ],
    })
    poll.mockResolvedValue({ trial: done, trials_left_today: 5 })
    vi.mocked(api.models.manage).mockResolvedValue(snap({ trial: done, trials_left_today: 5 }))
    await waitFor(() => expect(screen.getByText('Low score 6/12')).toBeInTheDocument(), { timeout: 5000 })
    expect(screen.getByText(/not one to put on the menu/)).toBeInTheDocument()
    await userEvent.click(screen.getByText('What it got wrong'))
    expect(screen.getByText("an event, then 'no, thursday': swim: 2 events, wanted 1")).toBeInTheDocument()
  })

  it('cancels a trial', async () => {
    vi.mocked(api.models.manage).mockResolvedValue(snap({ trial: trial() }))
    vi.spyOn(api.models, 'trial').mockResolvedValue({ trial: trial(), trials_left_today: 5 })
    const cancel = vi.spyOn(api.models, 'cancelTrial').mockImplementation(async () => {
      vi.mocked(api.models.manage).mockResolvedValue(snap({ trial: trial({ status: 'cancelled', error: 'cancelled' }) }))
      return { cancelled: true, trial: null }
    })
    render(<Models />)
    await waitFor(() => expect(screen.getByText('Trying DeepSeek: 3 of 12 cases')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(cancel).toHaveBeenCalled()
    await waitFor(() => expect(screen.getByText('Last trial of DeepSeek was cancelled.')).toBeInTheDocument())
  })

  it('says why a trial did not finish', async () => {
    vi.mocked(api.models.manage).mockResolvedValue(snap({ trial: trial({ status: 'failed', error: 'the model did not answer: 404: gone' }), trials_left_today: 1 }))
    render(<Models />)
    await waitFor(() => expect(screen.getByText('Last trial of DeepSeek did not finish: the model did not answer: 404: gone.')).toBeInTheDocument())
    expect(screen.getByText('1 trial left today.')).toBeInTheDocument()
  })

  it('says when the day has no trials left', async () => {
    vi.spyOn(api.models, 'tryIt').mockRejectedValue(new api.ApiError(409, 'that is the 6 trials allowed in a day; try again tomorrow'))
    render(<Models />)
    await waitFor(() => expect(row('DeepSeek')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Try DeepSeek' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('6 trials allowed in a day'))
  })
})

describe('adding a model', () => {
  const entry = {
    id: 'openrouter/~deepseek/deepseek-flash-latest',
    name: 'DeepSeek: Flash (latest)',
    context_length: 1048576,
    tools: true,
    price_in: 0.05,
    price_out: 0.14,
    alias: true,
    recommended: true,
    alias_of_it: '',
    provider: 'DeepSeek, through OpenRouter',
    on_menu: false,
  }
  const pinned = { ...entry, id: 'openrouter/deepseek/deepseek-flash-0731', name: 'DeepSeek: Flash 0731', alias: false, recommended: false, alias_of_it: entry.id, tools: false, price_in: null, price_out: null }

  it('searches the catalogue, recommends the moving name, and adds with a name and a line', async () => {
    const search = vi.spyOn(api.models, 'catalogue').mockResolvedValue({ configured: true, source: 'openrouter.ai', models: [entry, pinned], error: '' })
    const added = model({ ...cloud, id: entry.id, name: 'DeepSeek latest', enabled: false, trial: null })
    const add = vi.spyOn(api.models, 'add').mockResolvedValue({ ...snap({ models: [model(), added] }), added: entry.id, trial_started: false, note: 'that is the 6 trials allowed in a day' })
    render(<Models />)
    await userEvent.type(await screen.findByLabelText("Search openrouter.ai's models"), 'deepseek')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(search).toHaveBeenCalledWith('deepseek', expect.any(AbortSignal))
    const list = await screen.findByRole('list', { name: 'Catalogue' })
    expect(within(list).getByText('Always the newest version')).toBeInTheDocument()
    expect(within(list).getByText('1M tokens · takes tools · $0.050 in / $0.14 out per M · DeepSeek, through OpenRouter')).toBeInTheDocument()
    expect(within(list).getByText('No tools')).toBeInTheDocument()
    expect(within(list).getByText(/follows the newest/)).toBeInTheDocument()
    await userEvent.click(within(list).getByRole('button', { name: 'Add DeepSeek: Flash (latest)' }))
    const form = screen.getByRole('form', { name: 'Add a model' })
    const name = within(form).getByLabelText('Name')
    expect(name).toHaveValue('DeepSeek: Flash (latest)')
    await userEvent.clear(name)
    await userEvent.type(name, 'DeepSeek latest')
    await userEvent.click(within(form).getByRole('button', { name: 'Add and try it' }))
    expect(add).toHaveBeenCalledWith({ id: entry.id, name: 'DeepSeek latest', about: 'Runs at DeepSeek, through OpenRouter: what you ask is sent there.', local: false })
    await waitFor(() => expect(screen.getByText(/DeepSeek latest is on the list, off the menu until you turn it on. Not tried: that is the 6/)).toBeInTheDocument())
  })

  it('adds by id, marked as one at home, and starts its trial', async () => {
    const add = vi.spyOn(api.models, 'add').mockResolvedValue({ ...snap({ trial: trial({ model: 'my-local', done: 0 }) }), added: 'my-local', trial_started: true, note: '' })
    vi.spyOn(api.models, 'trial').mockResolvedValue({ trial: trial({ model: 'my-local', done: 0 }), trials_left_today: 5 })
    render(<Models />)
    await userEvent.type(await screen.findByLabelText('Or by its id'), 'my-local')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    const form = screen.getByRole('form', { name: 'Add a model' })
    await userEvent.click(within(form).getByRole('checkbox'))
    await userEvent.click(within(form).getByRole('button', { name: 'Add and try it' }))
    expect(add).toHaveBeenCalledWith({ id: 'my-local', name: 'my-local', about: '', local: true })
    await waitFor(() => expect(screen.getByText(/Trying it now/)).toBeInTheDocument())
  })

  it('says when the catalogue cannot be read, or has nothing', async () => {
    const search = vi.spyOn(api.models, 'catalogue').mockResolvedValue({ configured: true, source: 'openrouter.ai', models: [], error: 'could not reach openrouter.ai (ConnectError)' })
    render(<Models />)
    await userEvent.click(await screen.findByRole('button', { name: 'Search' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('could not reach openrouter.ai'))
    search.mockResolvedValue({ configured: true, source: 'openrouter.ai', models: [], error: '' })
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(screen.getByText('Nothing matches.')).toBeInTheDocument())
    search.mockRejectedValue(new api.ApiError(403, 'only the owner can do that'))
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('only the owner'))
  })

  it('offers only the id without a catalogue, and a cancel', async () => {
    vi.mocked(api.models.manage).mockResolvedValue(snap({ catalogue: { configured: false, source: '' } }))
    render(<Models />)
    await waitFor(() => expect(screen.getByText('No catalogue to search: add a model by its id.')).toBeInTheDocument())
    await userEvent.type(screen.getByLabelText('Or by its id'), 'x/y')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await userEvent.click(within(screen.getByRole('form', { name: 'Add a model' })).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('form', { name: 'Add a model' })).not.toBeInTheDocument()
  })
})

describe('the small words', () => {
  it('says context, price and score the way a person reads them', () => {
    expect(contextLabel(1048576)).toBe('1M tokens')
    expect(contextLabel(131072)).toBe('131K tokens')
    expect(contextLabel(null)).toBe('')
    expect(priceLabel(null, null)).toBe('')
    expect(priceLabel(0, 2.5)).toBe('free in / $2.50 out per M')
    expect(priceLabel(0.3, null)).toBe('$0.30 in / ? out per M')
    expect(verdictLabel({ passed: 11, total: 12, verdict: 'fair' })).toBe('Mostly right 11/12')
    expect(verdictLabel({ passed: 3, total: 12, verdict: null })).toBe('3/12')
  })

  it('moves one model and nothing else', () => {
    expect(moved(['a', 'b', 'c'], 'b', -1)).toEqual(['b', 'a', 'c'])
    expect(moved(['a', 'b', 'c'], 'c', 1)).toEqual(['a', 'b', 'c'])
    expect(moved(['a', 'b'], 'z', 1)).toEqual(['a', 'b'])
  })

  it('polls only while a trial runs', async () => {
    const poll = vi.spyOn(api.models, 'trial')
    render(<Models />)
    await waitFor(() => expect(row('DeepSeek')).toBeInTheDocument())
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50))
    })
    expect(poll).not.toHaveBeenCalled()
  })
})
