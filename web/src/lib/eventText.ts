import type { BoardLang } from './boardText'

/**
 * The event sheet's words. The app speaks English; the house board opens the same
 * sheet in the language its owner gave it, so on a Hebrew board it was the one
 * English, left-to-right thing on the wall.
 */
export interface EventText {
  event: string
  newEvent: string
  editEvent: string
  close: string
  keepIt: string
  thisEvent: string
  allEvents: string
  deleteForReal: string
  delete: string
  edit: string
  back: string
  cancel: string
  save: string
  add: string
  untitled: string
  invitationFrom: (organizer: string) => string
  readOnlyCalendar: string
  forNames: (names: string) => string
  deleteWhich: string
  saveWhich: string
  openInGoogle: string
  title: string
  allDay: string
  from: string
  to: string
  starts: string
  ends: string
  repeats: string
  repeat: { none: string; daily: string; weekly: string; biweekly: string; monthly: string; yearly: string }
  kept: string
  changesEvery: string
  location: string
  calendar: string
  invite: string
  inviteHintNew: string
  inviteHintEdit: string
  notes: string
  timesIn: (tz: string) => string
  giveTitle: string
  endBeforeStart: string
  who: string
  everyone: string
  onBoard: (names: string, first: string) => string
  invited: (names: string, many: boolean) => string
}

const en: EventText = {
  event: 'Event',
  newEvent: 'New event',
  editEvent: 'Edit event',
  close: 'Close',
  keepIt: 'Keep it',
  thisEvent: 'This event',
  allEvents: 'All events',
  deleteForReal: 'Delete for real',
  delete: 'Delete',
  edit: 'Edit',
  back: 'Back',
  cancel: 'Cancel',
  save: 'Save',
  add: 'Add',
  untitled: '(untitled)',
  invitationFrom: (o) => `An invitation from ${o}. Only they can change it — reply to it in Google Calendar.`,
  readOnlyCalendar: 'From a calendar luach only reads. It holds the time; what it is stays where it lives.',
  forNames: (n) => `For ${n}`,
  deleteWhich: 'It repeats. Delete only this one, or every one?',
  saveWhich: 'It repeats. Save this change for this event only, or for every one?',
  openInGoogle: 'Open in Google Calendar',
  title: 'Title',
  allDay: 'All day',
  from: 'From',
  to: 'To',
  starts: 'Starts',
  ends: 'Ends',
  repeats: 'Repeats',
  repeat: { none: 'Does not repeat', daily: 'Every day', weekly: 'Every week', biweekly: 'Every two weeks', monthly: 'Every month', yearly: 'Every year' },
  kept: '(kept)',
  changesEvery: 'Changing this changes every occurrence, past and future.',
  location: 'Location',
  calendar: 'Calendar',
  invite: 'Invite',
  inviteHintNew: 'Prefilled with the household’s usual people and your “also notify” addresses; remove anyone who should not get this one.',
  inviteHintEdit: 'Everyone here gets a Google Calendar invitation.',
  notes: 'Notes',
  timesIn: (tz) => `Times are in ${tz}.`,
  giveTitle: 'Give it a title.',
  endBeforeStart: 'The end is before the start.',
  who: 'For',
  everyone: 'Everyone',
  onBoard: (names, first) => `On ${names}’s board, in ${first}’s colour.`,
  invited: (names, many) => `${names} ${many ? 'are' : 'is'} invited.`,
}

const es: EventText = {
  event: 'Evento',
  newEvent: 'Nuevo evento',
  editEvent: 'Editar evento',
  close: 'Cerrar',
  keepIt: 'Conservarlo',
  thisEvent: 'Solo este',
  allEvents: 'Todos',
  deleteForReal: 'Borrar del todo',
  delete: 'Borrar',
  edit: 'Editar',
  back: 'Atrás',
  cancel: 'Cancelar',
  save: 'Guardar',
  add: 'Añadir',
  untitled: '(sin título)',
  invitationFrom: (o) => `Una invitación de ${o}. Solo quien la envió puede cambiarla: respóndela en Google Calendar.`,
  readOnlyCalendar: 'De un calendario que luach solo lee. Ocupa ese tiempo; lo demás se cambia donde está.',
  forNames: (n) => `Para ${n}`,
  deleteWhich: 'Se repite. ¿Borrar solo este o todos?',
  saveWhich: 'Se repite. ¿Guardar este cambio solo para este o para todos?',
  openInGoogle: 'Abrir en Google Calendar',
  title: 'Título',
  allDay: 'Todo el día',
  from: 'Desde',
  to: 'Hasta',
  starts: 'Empieza',
  ends: 'Termina',
  repeats: 'Se repite',
  repeat: { none: 'No se repite', daily: 'Cada día', weekly: 'Cada semana', biweekly: 'Cada dos semanas', monthly: 'Cada mes', yearly: 'Cada año' },
  kept: '(se mantiene)',
  changesEvery: 'Cambiar esto cambia todas las repeticiones, pasadas y futuras.',
  location: 'Lugar',
  calendar: 'Calendario',
  invite: 'Invitar',
  inviteHintNew: 'Con las personas habituales de la casa y tus direcciones de aviso; quita a quien no deba recibir esta.',
  inviteHintEdit: 'Todas estas personas reciben una invitación de Google Calendar.',
  notes: 'Notas',
  timesIn: (tz) => `Las horas son de ${tz}.`,
  giveTitle: 'Ponle un título.',
  endBeforeStart: 'El final es anterior al inicio.',
  who: 'Para',
  everyone: 'Todos',
  onBoard: (names, first) => `En el tablero de ${names}, con el color de ${first}.`,
  invited: (names) => `Se invita a ${names}.`,
}

const he: EventText = {
  event: 'אירוע',
  newEvent: 'אירוע חדש',
  editEvent: 'עריכת אירוע',
  close: 'סגירה',
  keepIt: 'להשאיר',
  thisEvent: 'רק את זה',
  allEvents: 'את כולם',
  deleteForReal: 'מחיקה סופית',
  delete: 'מחיקה',
  edit: 'עריכה',
  back: 'חזרה',
  cancel: 'ביטול',
  save: 'שמירה',
  add: 'הוספה',
  untitled: '(ללא שם)',
  invitationFrom: (o) => `הזמנה מ־${o}. רק השולח יכול לשנות אותה — השיבו עליה ב־Google Calendar.`,
  readOnlyCalendar: 'מיומן ש־luach רק קורא. הזמן תפוס; את הפרטים משנים במקום שבו הם נמצאים.',
  forNames: (n) => `עבור ${n}`,
  deleteWhich: 'האירוע חוזר. למחוק רק את זה, או את כולם?',
  saveWhich: 'האירוע חוזר. לשמור את השינוי רק לאירוע הזה, או לכולם?',
  openInGoogle: 'פתיחה ב־Google Calendar',
  title: 'שם',
  allDay: 'כל היום',
  from: 'מתאריך',
  to: 'עד תאריך',
  starts: 'התחלה',
  ends: 'סיום',
  repeats: 'חזרה',
  repeat: { none: 'לא חוזר', daily: 'כל יום', weekly: 'כל שבוע', biweekly: 'כל שבועיים', monthly: 'כל חודש', yearly: 'כל שנה' },
  kept: '(נשמר)',
  changesEvery: 'שינוי כאן משנה את כל המופעים, שעברו ושיבואו.',
  location: 'מקום',
  calendar: 'יומן',
  invite: 'הזמנה',
  inviteHintNew: 'מולא מראש באנשים הקבועים של הבית ובכתובות שלכם; הסירו את מי שלא צריך לקבל את זה.',
  inviteHintEdit: 'כל מי שכאן מקבל הזמנה ב־Google Calendar.',
  notes: 'הערות',
  timesIn: (tz) => `השעות לפי ${tz}.`,
  giveTitle: 'תנו לו שם.',
  endBeforeStart: 'הסיום לפני ההתחלה.',
  who: 'עבור',
  everyone: 'כולם',
  onBoard: (names, first) => `בלוח של ${names}, בצבע של ${first}.`,
  invited: (names) => `גם ${names} מקבלים הזמנה.`,
}

export const EVENT_TEXT: Record<BoardLang, EventText> = { en, es, he }
