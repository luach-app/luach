import { describe, expect, it } from 'vitest'
import { BOARD_LANGUAGES, BOARD_TEXT, boardLocale, describeChoreDays, resolveBoardLang, weekOf } from '../boardText'

const LANGS = ['en', 'es', 'he'] as const

describe('the board’s words', () => {
  it('every language has every word', () => {
    const keys = Object.keys(BOARD_TEXT.en).sort()
    const initials = Object.keys(BOARD_TEXT.en.dayInitials).sort()
    for (const l of LANGS) {
      expect(Object.keys(BOARD_TEXT[l]).sort(), l).toEqual(keys)
      expect(Object.keys(BOARD_TEXT[l].dayInitials).sort(), l).toEqual(initials)
    }
  })

  it('no word is left empty, and each one with a gap fills it', () => {
    for (const l of LANGS) {
      for (const [key, value] of Object.entries(BOARD_TEXT[l])) {
        if (typeof value === 'function') expect((value as (...a: unknown[]) => string)('Lily', 'why'), `${l}.${key}`).toContain('Lily')
        else if (typeof value === 'string') expect(value.trim(), `${l}.${key}`).not.toBe('')
      }
    }
  })

  it('offers the four choices the server accepts', () => {
    expect(BOARD_LANGUAGES.map((l) => l.value)).toEqual(['auto', 'en', 'es', 'he'])
  })
})

describe('which language a board speaks', () => {
  it('is the owner’s choice when there is one', () => {
    expect(resolveBoardLang('he', 'en-US')).toBe('he')
    expect(resolveBoardLang('es', 'he-IL')).toBe('es')
    expect(resolveBoardLang('en', 'es')).toBe('en')
  })

  it('on auto, is the browser’s, and English for anything it does not speak', () => {
    expect(resolveBoardLang('auto', 'he-IL')).toBe('he')
    expect(resolveBoardLang('auto', 'iw')).toBe('he')
    expect(resolveBoardLang('auto', 'es-419')).toBe('es')
    expect(resolveBoardLang(undefined, 'es_ES')).toBe('es')
    expect(resolveBoardLang('auto', 'fr-FR')).toBe('en')
    expect(resolveBoardLang('auto', '')).toBe('en')
    expect(resolveBoardLang('klingon', 'de')).toBe('en')
  })

  it('reads right to left only in Hebrew, and on a 24-hour clock outside English', () => {
    expect(boardLocale('he')).toMatchObject({ dir: 'rtl', locale: 'he-IL', hourCycle: 'h23' })
    expect(boardLocale('es')).toMatchObject({ dir: 'ltr', locale: 'es', hourCycle: 'h23' })
    expect(boardLocale('en')).toMatchObject({ dir: 'ltr', locale: 'en', hourCycle: undefined })
  })

  it('lays the week out as the language does, and says a chore’s days in it', () => {
    expect(weekOf(BOARD_TEXT.he)[0]).toBe('SU')
    expect(weekOf(BOARD_TEXT.es)[0]).toBe('MO')
    expect(describeChoreDays(['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'], boardLocale('he'))).toBe('כל יום')
    expect(describeChoreDays(['MO', 'WE'], boardLocale('es'))).toBe('lun, mié')
    expect(describeChoreDays(['SA', 'SU'], boardLocale('en'))).toBe('weekends')
  })
})
