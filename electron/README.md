# Saignes-en-Padaine — AppImage build

Packages the Django dashboard + `weather_mqtt.py --service` (the same code
the `saignes-dashboard.service`/`saignes-weather.service` systemd units run)
into a single self-contained `.AppImage`, with its own bundled Python venv
so the target machine doesn't need Python/Django/etc. pre-installed. Runs
standalone — no separate always-on service needed elsewhere. The existing
systemd deployment is untouched by any of this; this is an additional
packaging target, not a replacement.

## Build

```sh
cd electron
npm install
npm run build        # stages the backend (build-backend.sh) then runs electron-builder
```

Produces `electron/dist/Saignes-en-Padaine-<version>.AppImage`.

`npm run build` always wipes and rebuilds `electron/resources/` from
scratch first (via `build-backend.sh`) — it copies a clean snapshot of
`core/`, `dashboard/`, `static/`, `templates/`, `weather_mqtt.py`,
`manage.py`, `requirements.txt` from the parent project, and builds a fresh
venv from `requirements.txt`. Nothing from this dev machine's own
`data/`/`db.sqlite3` is ever included.

**Glibc caveat**: the bundled venv's Python is whatever `python3 -m venv`
resolves to on the *build* machine — build on a reasonably old/compatible
base (e.g. Ubuntu 20.04/22.04) if you want the AppImage to run on a wide
range of target distros, and spot-check on a couple before distributing.

## Run

```sh
chmod +x Saignes-en-Padaine-*.AppImage
./Saignes-en-Padaine-*.AppImage
```

First launch: runs `manage.py migrate`, starts the dashboard on
`127.0.0.1:8080` (loopback only — this is a single-machine desktop app, and
every `/api/*` endpoint including config writes is unauthenticated) and
`weather_mqtt.py --service`, then opens a window once the dashboard
responds. All runtime data (the SQLite DB, weather cache, site config, etc.)
lives under `~/.config/Saignes-en-Padaine/` (`app.getPath('userData')`), not
inside the AppImage itself.

**Closing the window does not stop the app** — it hides to the tray icon,
because `weather_mqtt.py --service` is what actually publishes irrigation
commands on its own schedule and should keep running whether or not the
window is open. Use the tray icon's "Quit" to actually stop both backend
processes.

## Dev mode (without packaging)

```sh
cd electron
bash build-backend.sh   # stage resources/app + resources/venv once
npm install
npm start                # electron . -- reads from ./resources/ directly
```

## Not yet done
- Auto-launch on login (would need a `.desktop` file in
  `~/.config/autostart/` — not wired up by this build).
- Windows/Mac packaging — out of scope, Linux AppImage only.
