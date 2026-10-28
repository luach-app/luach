import { useEffect, useState } from 'react'
import { api } from './api'

/**
 * Which model answers. A short menu from the server — the owner adds, tries and
 * enables each model on it — and the choice is the member's, saved on their
 * account (PATCH /api/auth/me), so it follows them to every screen and door.
 */
export interface ModelHealth {
  status: 'ok' | 'not_answering'
  since: string | null
  reason: string
}

export interface ModelChoice {
  id: string
  name: string
  about: string
  /** Runs on the household's own computer: nothing leaves the house. */
  local?: boolean
  /** Who answers a cloud model ("Google, through OpenRouter"); "" for a local one. */
  provider?: string
  health?: ModelHealth
}

export interface ModelMenu {
  options: ModelChoice[]
  defaultModel: string
}

export const answering = (m: { health?: ModelHealth }) => (m.health?.status ?? 'ok') === 'ok'

export function useModels(): ModelMenu {
  const [menu, setMenu] = useState<ModelMenu>({ options: [], defaultModel: '' })
  useEffect(() => {
    let alive = true
    api.get<{ catalogue?: ModelChoice[]; default?: string }>('/api/models').then(
      (r) => alive && setMenu({ options: r.catalogue ?? [], defaultModel: r.default ?? '' }),
      // No menu is not an error a person needs: the setting simply hides and
      // the household's own model answers.
      () => undefined,
    )
    return () => {
      alive = false
    }
  }, [])
  return menu
}

/* ---- the owner's management (Settings › Household › Models) --------------- */

export type Verdict = 'good' | 'fair' | 'low'

export interface ManagedModel extends ModelChoice {
  provider_set: string
  enabled: boolean
  position: number
  is_default: boolean
  meta: { context_length?: number; tools?: boolean; price_in?: number; price_out?: number }
  failures: number
  last_ok_at: string | null
  trial: { passed: number; total: number; verdict: Verdict; at: string | null } | null
}

export interface TrialCase {
  case: string
  about: string
  ok: boolean
  problems: string[]
  tools: string[][]
}

export interface ModelTrial {
  id: number
  model: string
  status: 'running' | 'done' | 'failed' | 'cancelled'
  requested_by: string
  started_at: string | null
  finished_at: string | null
  done: number
  passed: number
  total: number
  verdict: Verdict | null
  cases: TrialCase[]
  error: string
}

export interface ModelsSnapshot {
  default: string
  configured: boolean
  models: ManagedModel[]
  trial: ModelTrial | null
  trials_left_today: number
  catalogue: { configured: boolean; source: string }
}

export interface CatalogueEntry {
  id: string
  name: string
  context_length: number | null
  tools: boolean | null
  price_in: number | null
  price_out: number | null
  alias: boolean
  recommended: boolean
  alias_of_it: string
  provider: string
  on_menu: boolean
}

export interface CatalogueAnswer {
  configured: boolean
  source: string
  models: CatalogueEntry[]
  error: string
}

/** "1M tokens", "128K tokens". */
export function contextLabel(n: number | null | undefined): string {
  if (!n) return ''
  if (n >= 1_000_000) return `${Math.round(n / 100_000) / 10}M tokens`
  return `${Math.round(n / 1000)}K tokens`
}

/** "$0.30 / $2.50 per M" — in, out; "" when the catalogue gives no price. */
export function priceLabel(i: number | null | undefined, o: number | null | undefined): string {
  if (i == null && o == null) return ''
  const f = (v: number | null | undefined) => (v == null ? '?' : v === 0 ? 'free' : `$${v < 0.1 ? v.toFixed(3) : v.toFixed(2)}`)
  return `${f(i)} in / ${f(o)} out per M`
}

/** What a trial's score means, said plainly. */
export function verdictLabel(t: { passed: number; total: number; verdict: Verdict | null }): string {
  const score = `${t.passed}/${t.total}`
  if (t.verdict === 'good') return `Passed ${score}`
  if (t.verdict === 'fair') return `Mostly right ${score}`
  if (t.verdict === 'low') return `Low score ${score}`
  return score
}

/** The list with one model moved up (-1) or down (+1). */
export function moved(ids: string[], id: string, by: -1 | 1): string[] {
  const at = ids.indexOf(id)
  const to = at + by
  if (at < 0 || to < 0 || to >= ids.length) return ids
  const next = [...ids]
  ;[next[at], next[to]] = [next[to] as string, next[at] as string]
  return next
}
