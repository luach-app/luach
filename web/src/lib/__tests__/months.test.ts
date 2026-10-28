import { describe, expect, it } from 'vitest'
import { addMonths, formatMonthYear, monthGrid, weekdayMon, weekdayNames, ymOf } from '../months'

describe('a month as a grid', () => {
  it('starts on a Monday and covers whole weeks', () => {
    const g = monthGrid('2026-09')
    expect(g.ym).toBe('2026-09')
    expect(g.weeks.length).toBeGreaterThanOrEqual(5)
    expect(g.weeks.every((w) => w.length === 7)).toBe(true)
    expect(weekdayMon(g.first)).toBe(0)
    // September 2026 begins on a Tuesday, so the grid opens on 31 August.
    expect(g.first).toBe('2026-08-31')
    expect(g.weeks.flat()).toContain('2026-09-01')
    expect(g.weeks.flat()).toContain('2026-09-30')
    expect(g.last >= '2026-09-30').toBe(true)
  })

  it('handles February, leap and otherwise', () => {
    expect(monthGrid('2024-02').weeks.flat()).toContain('2024-02-29')
    expect(monthGrid('2026-02').weeks.flat()).not.toContain('2026-02-29')
  })

  it('walks months across a year boundary', () => {
    expect(addMonths('2026-12', 1)).toBe('2027-01')
    expect(addMonths('2026-01', -1)).toBe('2025-12')
    expect(addMonths('2026-09', 4)).toBe('2027-01')
  })

  it('names things for people', () => {
    expect(ymOf('2026-09-17')).toBe('2026-09')
    expect(formatMonthYear('2026-09', 'en')).toMatch(/September 2026/)
    expect(weekdayNames('en', 'short')).toHaveLength(7)
    expect(weekdayNames('en', 'narrow')[0]).toBeTruthy()
  })
})
