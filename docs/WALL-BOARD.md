# Wall board

A screen in the kitchen, or by the door, that shows the household's day: everyone's events
and tasks side by side, to read at a glance and to tap.

## What /board is

The board is a page of the web app, `/board` on your luach's address (for example
`https://calendar.example.com/board`). It is made for a touch screen that stays on:

- a column for each person in the family, plus one for the whole family;
- today first, and the next 14 days one tap away, by the day chips, the arrows or a swipe;
- tap an event or a task to open it, tick a task done, or add something;
- **hold and drag**: hold an event or a task for about half a second, then drop it on
  someone's column to make it theirs, or on a day chip to move it to that day (keeping its
  time). **Undo** stays on screen for six seconds. Something that repeats says to change it
  in the editor, and an invitation from someone else cannot be moved;
- its own language, set per board: English, Spanish or Hebrew, or Automatic to follow the
  screen's own. In Hebrew the whole board reads right to left;
- it keeps the screen awake while it shows, where the browser allows it;
- it updates itself: after you upgrade luach, a paired board reloads once nobody has
  touched it for a minute.

A board is not a member. It never holds a session; it holds a token of its own that opens
nothing outside the board, and what is done on it is recorded on the audit trail as
`board:<its name>`. A member who opens `/board` while signed in sees the same page, with
nothing to pair, and their ticks are recorded as theirs.

## Pairing a screen

1. On the screen, open `/board`. It shows a six-character code.
2. On your phone or computer, signed in as the owner, open **Members › House boards**,
   type the code, name the board ("Kitchen"), and choose **Pair**. Codes last ten minutes.
3. The screen shows the day. Under **House boards** you can then choose the board's
   language, and whether anyone at it can add, change and remove things or only tick tasks
   done (the default is that they can).

Removing a board there unpairs the screen, which goes back to showing a code.

## Choosing a screen

Anything that runs an ordinary, current browser full-screen can be a board. What matters:

- **It runs a browser you can lock to one page.** On Android, a kiosk browser (below) keeps
  the board on screen, starts it after a power cut and puts the screen to sleep at night.
  A dedicated "family calendar" device that only runs its maker's own app cannot run luach;
  one that can switch to plain Android with Google Play can.
- **Touch, with several points.** Ticking needs one finger; hold-and-drag needs a screen
  that reports a held finger reliably. Try it on the real screen before you settle on it.
- **Size for the distance.** A board read from across a kitchen wants about 21" or more; one
  on a counter, read from arm's length, can be 13–16". The columns get narrower with every
  person in the family, so a larger household wants a wider screen.
- **Always on.** An LCD (IPS) panel, not OLED: a page that sits still for hours burns into
  an OLED screen. A matte finish keeps window reflections down, and an ambient light sensor
  lets it dim in the evening.
- **Power.** A board runs all day, so plan for it to be plugged in. A screen with a battery
  still needs the plug; a battery only helps if the board moves around the house.
- **Mounting.** A wall screen usually takes a VESA mount (often 100 × 100); a slim fixed
  mount keeps it close to the wall. Plan the cable: an outlet behind the screen, a spot just
  above an existing outlet, or a paintable cord cover. A screen with a stand, or a tablet on
  one, can live on a counter instead. Taping a sheet of paper the size of the screen where it
  would go, and living with it for a day, settles most questions of size and place.

A ~13" LCD Android tablet on a stand is the simplest start; a dedicated wall display running
Android with Google Play is the tidiest.

## Setting up the kiosk

### Android, with Fully Kiosk Browser

1. Connect the device to Wi-Fi and sign in to Google Play.
2. Install **Fully Kiosk Browser**.
3. Set its start URL to your board, `https://<your luach>/board`.
4. Turn on **Launch on boot**, so the board comes back after a power cut.
5. Set the screen to turn off at night and on in the morning (its schedule settings).
6. Pair the board as above.

### Any other kiosk browser

The board needs nothing more than a browser that stays on `/board`: Chrome in kiosk mode on
a small computer, Guided Access on an iPad, or a smart display's own browser. Whatever it is,
it should start on the board by itself and keep its storage: the board keeps its token in
the browser's local storage, and a browser that clears it on every start will ask to be
paired again.

Point it at the same HTTPS address members use (see [SELF-HOSTING.md](SELF-HOSTING.md)).

If hold-and-drag feels slow to lift or the page scrolls instead, the timings are in
`web/src/lib/boardDrag.ts` (450 ms to lift, 8 px of movement allowed while holding).
