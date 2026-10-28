# Contributing

Thank you for helping. luach is small and opinionated; an issue describing what you want to
change, before a large pull request, saves both of us time.

## Setup

You need Python 3.12+, [hatch](https://hatch.pypa.io) (`pipx install hatch`), Docker for the
test database, and Node 24 for the web app.

```bash
hatch run pg          # a throwaway Postgres 16 on 127.0.0.1:55437, gone when stopped
hatch run check       # builds the environment from requirements-dev.lock, then runs everything
cd web && npm ci
```

The README's Development section shows how to run the server and the web app locally.

## What a pull request must pass

CI runs these on every pull request, and a red one is not merged:

- **backend**: `scripts/lock.sh --check`, then `hatch run lint` (ruff, ruff format),
  `hatch run typecheck` (mypy) and `hatch run cov` (pytest with the 85% coverage floor).
  `hatch run check` runs the last three locally.
- **web**, in `web/`: `npm run typecheck`, `npm run lint`, `npm run coverage` (the screens'
  tests with their floor) and `npm run build`. `web/dist` is built, never committed.

A change to the Dockerfile or the image also runs the integration suite (`ci/integration`).

## Rules worth knowing

- **Every write goes through the gate.** Writes to the calendar go through the admission gate
  in `src/luach/agent/control.py`. A new write tool is added to `WRITE_TOOLS` in
  `src/luach/agent/tools.py` and given labels in `control.labels_for`. Never register a write
  tool on the agent that bypasses the gate.
- **The schema is Alembic's.** The store is Postgres; its schema lives in
  `src/luach/migrations`. A schema change is a model change in `src/luach/db.py` plus a
  revision: `hatch run revision "what changes"` autogenerates one against `hatch run pg`'s
  database. Read it before committing. `luach-migrate` brings a database to head, and the app
  refuses to start on a schema it does not know.
- **Dependencies are locked.** A dependency change is `pyproject.toml` plus `scripts/lock.sh`,
  with both lock files committed in the same change. CI refuses a `pyproject.toml` change whose
  locks were not refreshed.
- **Tests do not depend on the date.** Inject `now` rather than comparing fixed times with the
  wall clock, and do not build a fixture whose meaning depends on today's weekday.
- **Settings are environment variables**, read in `src/luach/config.py`. A new one goes there,
  in `.env.example`, and in `docs/SELF-HOSTING.md` if a self-hoster needs to know it.

## Commits

- One change per pull request, with a message that says what changed and why, in plain
  sentences. The subject line stands on its own; the body explains what the diff cannot.
- Commits carry their author's own name and email.
- Keep unrelated formatting and refactoring out of a change; send it separately.

## License

luach is licensed under the [GNU Affero General Public License v3.0 or later](LICENSE).
Contributions are accepted under the same license: by opening a pull request, you agree that
your contribution is licensed under AGPL-3.0-or-later. There is no contributor license
agreement.

## Security

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).
