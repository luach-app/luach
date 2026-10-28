/**
 * The house board's own words, in each language a board can speak.
 *
 * Only the board is translated: a screen on a kitchen wall is read by everyone
 * in the house, while the rest of luach is read by the members who set it up.
 * The owner picks a board's language under Members › House boards; "auto"
 * follows the screen's own browser.
 *
 * Names and titles are not here — they are the family's own words, and are
 * shown as they were written, each in its own direction.
 */

export type BoardLang = 'en' | 'es' | 'he'
/** What the owner can choose for a board; "auto" is the screen's own browser. */
export type BoardLanguage = 'auto' | BoardLang

export const BOARD_LANGUAGES: { value: BoardLanguage; label: string }[] = [
  { value: 'auto', label: 'Automatic' },
  { value: 'en', label: 'English' },
  { value: 'es', label: 'Español' },
  { value: 'he', label: 'עברית' },
]

type DayCode = 'MO' | 'TU' | 'WE' | 'TH' | 'FR' | 'SA' | 'SU'

export interface BoardText {
  today: string
  tomorrow: string
  /** The footer on a later page: the day after the one shown, whichever it is. */
  dayAfter: string
  previousDay: string
  nextDay: string
  /** The chip row's name, for a screen reader. */
  days: string
  backToToday: string
  offline: string
  openFullScreen: string
  makeWallBoard: string
  addFor: (name: string) => string
  addForFamily: string
  /** The shared column's heading. */
  family: string
  familysDay: string
  event: string
  task: string
  freeDay: string
  allDay: string
  open: (title: string) => string
  couldNotOpen: string
  noOneYet: string
  more: (n: number) => string
  didNotSave: (title: string, why: string) => string
  unreachable: string
  // The pairing screen.
  pairTitle: string
  pairHow: string
  pairChanges: string
  pairingCode: (spelled: string) => string
  // A task's line.
  late: (due: string) => string
  dueOn: (due: string) => string
  everyDay: string
  weekdays: string
  weekends: string
  // A task opened on the board.
  taskTitle: string
  aTaskFor: (name: string) => string
  aTask: string
  what: string
  somethingToDo: string
  who: string
  taskFor: string
  anyone: string
  repeats: string
  repeatsOn: string
  dueOptional: string
  addTask: string
  save: string
  remove: string
  keep: string
  cancel: string
  close: string
  giveItAName: string
  pickTheDays: string
  // Holding something and carrying it to someone else, or to another day.
  /** Said to a screen reader the moment a long press lifts it. */
  pickedUp: (title: string) => string
  handedTo: (title: string, name: string) => string
  handedToFamily: (title: string) => string
  /** `day` is a long date: "Thursday, September 24". */
  movedTo: (title: string, day: string) => string
  putBack: (title: string) => string
  undo: string
  repeatsUseEditor: string
  onlyOrganizer: string
  dayInitials: Record<DayCode, string>
  /** The week as this language lays it out: Sunday first in Hebrew. */
  weekStartsOn: 'MO' | 'SU'
}

const en: BoardText = {
  today: 'Today',
  tomorrow: 'Tomorrow',
  dayAfter: 'The day after',
  previousDay: 'Previous day',
  nextDay: 'Next day',
  days: 'Days',
  backToToday: 'Back to today',
  offline: 'offline — showing the last known day',
  openFullScreen: 'Open full screen',
  makeWallBoard: 'Make this screen a wall board',
  addFor: (name) => `Add for ${name}`,
  addForFamily: 'Add for the family',
  family: 'Family',
  familysDay: 'The family’s day',
  event: 'Event',
  task: 'Task',
  freeDay: 'A free day.',
  allDay: 'All day',
  open: (title) => `Open ${title}`,
  couldNotOpen: 'Could not open that.',
  noOneYet: 'No one is on the board yet. Whoever runs luach adds the people it shows: Members › Family on the web, or Settings › Household › Family on the iPhone.',
  more: (n) => `+${n} more`,
  didNotSave: (title, why) => `“${title}” did not save: ${why}`,
  unreachable: 'luach could not be reached.',
  pairTitle: 'Make this screen the house board',
  pairHow: 'In luach on your phone, open Members → House boards and type this code.',
  pairChanges: 'It changes every ten minutes.',
  pairingCode: (spelled) => `Pairing code ${spelled}`,
  late: (due) => `late — was due ${due}`,
  dueOn: (due) => `due ${due}`,
  everyDay: 'every day',
  weekdays: 'weekdays',
  weekends: 'weekends',
  taskTitle: 'Task',
  aTaskFor: (name) => `A task for ${name}`,
  aTask: 'A task',
  what: 'What',
  somethingToDo: 'Something to do',
  who: 'For',
  taskFor: 'Task for',
  anyone: 'Anyone',
  repeats: 'A chore that repeats',
  repeatsOn: 'Repeats on',
  dueOptional: 'Due (optional)',
  addTask: 'Add task',
  save: 'Save',
  remove: 'Remove',
  keep: 'Keep',
  cancel: 'Cancel',
  close: 'Close',
  giveItAName: 'Give it a name.',
  pickTheDays: 'Pick the days it falls on.',
  pickedUp: (title) => `Picked up ${title}. Drop it on a person or a day.`,
  handedTo: (title, name) => `${title} is now ${name}’s.`,
  handedToFamily: (title) => `${title} is now the family’s.`,
  movedTo: (title, day) => `${title} moved to ${day}.`,
  putBack: (title) => `${title} is back where it was.`,
  undo: 'Undo',
  repeatsUseEditor: 'This one repeats — change it in the editor.',
  onlyOrganizer: 'Only the organizer can change this.',
  dayInitials: { MO: 'M', TU: 'T', WE: 'W', TH: 'T', FR: 'F', SA: 'S', SU: 'S' },
  weekStartsOn: 'MO',
}

const es: BoardText = {
  today: 'Hoy',
  tomorrow: 'Mañana',
  dayAfter: 'Al día siguiente',
  previousDay: 'Día anterior',
  nextDay: 'Día siguiente',
  days: 'Días',
  backToToday: 'Volver a hoy',
  offline: 'sin conexión — se muestra el último día conocido',
  openFullScreen: 'Abrir a pantalla completa',
  makeWallBoard: 'Convertir esta pantalla en un tablero de pared',
  addFor: (name) => `Añadir para ${name}`,
  addForFamily: 'Añadir para la familia',
  family: 'Familia',
  familysDay: 'El día de la familia',
  event: 'Evento',
  task: 'Tarea',
  freeDay: 'Un día libre.',
  allDay: 'Todo el día',
  open: (title) => `Abrir ${title}`,
  couldNotOpen: 'No se pudo abrir.',
  noOneYet: 'Todavía no hay nadie en el tablero. Quien administra luach añade a las personas que muestra: Members › Family en la web, o Settings › Household › Family en el iPhone.',
  more: (n) => `+${n} más`,
  didNotSave: (title, why) => `«${title}» no se guardó: ${why}`,
  unreachable: 'No se pudo conectar con luach.',
  pairTitle: 'Convierte esta pantalla en el tablero de la casa',
  pairHow: 'En luach, desde tu teléfono, abre Members → House boards y escribe este código.',
  pairChanges: 'Cambia cada diez minutos.',
  pairingCode: (spelled) => `Código de emparejamiento ${spelled}`,
  late: (due) => `atrasada — era para el ${due}`,
  dueOn: (due) => `para el ${due}`,
  everyDay: 'todos los días',
  weekdays: 'de lunes a viernes',
  weekends: 'fines de semana',
  taskTitle: 'Tarea',
  aTaskFor: (name) => `Una tarea para ${name}`,
  aTask: 'Una tarea',
  what: 'Qué',
  somethingToDo: 'Algo que hacer',
  who: 'Para',
  taskFor: 'Tarea para',
  anyone: 'Cualquiera',
  repeats: 'Una tarea que se repite',
  repeatsOn: 'Se repite los',
  dueOptional: 'Para cuándo (opcional)',
  addTask: 'Añadir tarea',
  save: 'Guardar',
  remove: 'Quitar',
  keep: 'Conservar',
  cancel: 'Cancelar',
  close: 'Cerrar',
  giveItAName: 'Ponle un nombre.',
  pickTheDays: 'Elige los días en que toca.',
  pickedUp: (title) => `Has levantado ${title}. Suéltalo sobre una persona o un día.`,
  handedTo: (title, name) => `${title} ahora es de ${name}.`,
  handedToFamily: (title) => `${title} ahora es de la familia.`,
  movedTo: (title, day) => `${title} pasa al ${day}.`,
  putBack: (title) => `${title} ha vuelto a su sitio.`,
  undo: 'Deshacer',
  repeatsUseEditor: 'Se repite: cámbialo en el editor.',
  onlyOrganizer: 'Solo quien lo organiza puede cambiarlo.',
  dayInitials: { MO: 'L', TU: 'M', WE: 'X', TH: 'J', FR: 'V', SA: 'S', SU: 'D' },
  weekStartsOn: 'MO',
}

const he: BoardText = {
  today: 'היום',
  tomorrow: 'מחר',
  dayAfter: 'למחרת',
  previousDay: 'היום הקודם',
  nextDay: 'היום הבא',
  days: 'ימים',
  backToToday: 'חזרה להיום',
  offline: 'אין חיבור — מוצג היום האחרון שנטען',
  openFullScreen: 'פתיחה במסך מלא',
  makeWallBoard: 'הפיכת המסך הזה ללוח קיר',
  addFor: (name) => `הוספה ל־${name}`,
  addForFamily: 'הוספה למשפחה',
  family: 'משפחה',
  familysDay: 'היום של המשפחה',
  event: 'אירוע',
  task: 'משימה',
  freeDay: 'יום פנוי.',
  allDay: 'כל היום',
  open: (title) => `פתיחת ${title}`,
  couldNotOpen: 'לא הצלחנו לפתוח את זה.',
  noOneYet: 'עדיין אין אף אחד בלוח. מי שמנהל את luach מוסיף את האנשים שיופיעו בו: Members › Family באתר, או Settings › Household › Family באייפון.',
  more: (n) => `+${n} נוספים`,
  didNotSave: (title, why) => `"${title}" לא נשמרה: ${why}`,
  unreachable: 'אין קשר ל־luach.',
  pairTitle: 'הפכו את המסך הזה ללוח הבית',
  pairHow: 'ב־luach בטלפון, פתחו את Members → House boards והקלידו את הקוד הזה.',
  pairChanges: 'הקוד מתחלף כל עשר דקות.',
  pairingCode: (spelled) => `קוד צימוד ${spelled}`,
  late: (due) => `באיחור — היעד היה ${due}`,
  dueOn: (due) => `עד ${due}`,
  everyDay: 'כל יום',
  weekdays: 'שני עד שישי',
  weekends: 'שבת וראשון',
  taskTitle: 'משימה',
  aTaskFor: (name) => `משימה ל־${name}`,
  aTask: 'משימה',
  what: 'מה',
  somethingToDo: 'משהו לעשות',
  who: 'עבור',
  taskFor: 'משימה עבור',
  anyone: 'כל אחד',
  repeats: 'מטלה שחוזרת',
  repeatsOn: 'חוזרת בימים',
  dueOptional: 'עד מתי (לא חובה)',
  addTask: 'הוספת משימה',
  save: 'שמירה',
  remove: 'הסרה',
  keep: 'השארה',
  cancel: 'ביטול',
  close: 'סגירה',
  giveItAName: 'תנו לה שם.',
  pickTheDays: 'בחרו באילו ימים היא חלה.',
  pickedUp: (title) => `הרמתם את ${title}. שחררו על אדם או על יום.`,
  handedTo: (title, name) => `העברנו את ${title} אל ${name}.`,
  handedToFamily: (title) => `העברנו את ${title} למשפחה.`,
  movedTo: (title, day) => `הזזנו את ${title} ל${day}.`,
  putBack: (title) => `ביטלנו את ההזזה של ${title}.`,
  undo: 'ביטול פעולה',
  repeatsUseEditor: 'זה חוזר על עצמו — שנו את זה בחלון העריכה.',
  onlyOrganizer: 'רק מי שיצר את האירוע יכול לשנות אותו.',
  dayInitials: { MO: 'ב׳', TU: 'ג׳', WE: 'ד׳', TH: 'ה׳', FR: 'ו׳', SA: 'ש׳', SU: 'א׳' },
  weekStartsOn: 'SU',
}

export const BOARD_TEXT: Record<BoardLang, BoardText> = { en, es, he }

/** The language a board speaks: the owner's choice, or else the screen's browser. */
export function resolveBoardLang(setting: string | undefined, browser: string | undefined = typeof navigator === 'undefined' ? undefined : navigator.language): BoardLang {
  if (setting === 'en' || setting === 'es' || setting === 'he') return setting
  const primary = (browser ?? '').toLowerCase().split(/[-_]/)[0]
  // "iw" is the old code for Hebrew, and some Android browsers still send it.
  if (primary === 'he' || primary === 'iw') return 'he'
  if (primary === 'es') return 'es'
  return 'en'
}

export interface BoardLocale {
  lang: BoardLang
  /** For Intl: dates, weekdays, months and times. */
  locale: string
  dir: 'ltr' | 'rtl'
  /** A kitchen in Tel Aviv or Madrid reads a 24-hour clock. */
  hourCycle?: 'h23'
  t: BoardText
}

export function boardLocale(lang: BoardLang): BoardLocale {
  return {
    lang,
    locale: lang === 'he' ? 'he-IL' : lang,
    dir: lang === 'he' ? 'rtl' : 'ltr',
    hourCycle: lang === 'en' ? undefined : 'h23',
    t: BOARD_TEXT[lang],
  }
}

const ALL_DAYS: DayCode[] = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']

/** The week's days in the order this language lays them out. */
export function weekOf(t: BoardText): DayCode[] {
  return t.weekStartsOn === 'SU' ? ['SU', ...ALL_DAYS.slice(0, 6)] : ALL_DAYS
}

/** A weekday's full name, for a screen reader: "Monday", "lunes", "יום שני". */
export function weekdayName(code: string, locale: string, style: 'long' | 'short' = 'long'): string {
  const index = ALL_DAYS.indexOf(code as DayCode)
  if (index < 0) return code
  // 2024-01-01 was a Monday.
  return new Intl.DateTimeFormat(locale, { weekday: style, timeZone: 'UTC' }).format(new Date(Date.UTC(2024, 0, 1 + index)))
}

/** The days a chore falls on, as the board says them. */
export function describeChoreDays(days: string[], loc: BoardLocale): string {
  if (days.length === 7) return loc.t.everyDay
  if (days.join() === 'MO,TU,WE,TH,FR') return loc.t.weekdays
  if (days.join() === 'SA,SU') return loc.t.weekends
  return days.map((d) => weekdayName(d, loc.locale, 'short')).join(', ')
}

/** "Noa and Sam", "Noa y Sam", "Noa ו-Sam". */
export function joinNames(names: string[], locale: string): string {
  return new Intl.ListFormat(locale, { type: 'conjunction' }).format(names)
}

/** A YYYY-MM-DD date, short: "Sep 24", "24 sept", "24 בספט׳". */
export function shortDate(iso: string, locale: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso
  return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(`${iso}T12:00:00Z`))
}
