# Crew game-vote — self-hosted, ranked top-3

A tiny ranked poll (3-2-1 scoring) with pros/cons for self-hostable co-op
games. No dependencies: `server.py` is Python standard library only, ballots
are stored in a `votes.json` on a Docker volume.

## Files
- `server.py` — the whole backend (stdlib only). Serves `index.html` + a small vote API.
- `index.html` — the frontend (must sit next to `server.py`).
- `Dockerfile` — builds the app image (`python:3.12-slim`, no build step).
- `docker-compose.yml` — local dev: live-reloads source, persists ballots in a volume.
- `.github/workflows/docker.yml` — builds and pushes the image to GHCR on push to `main`.

## Local dev

```bash
docker compose up --build
# open http://127.0.0.1:8787
```

`server.py` and `index.html` are bind-mounted read-only, so edits show up on a
refresh without rebuilding. Ballots live in a named `votes` volume.

Reset the poll:
```bash
docker compose down -v
```

Prefer no Docker? The backend runs straight from Python:
```bash
VOTES_FILE=/tmp/votes.test.json PORT=8799 python3 server.py
# open http://127.0.0.1:8799
```

## Deploy

Every push to `main` builds and publishes an image to the GitHub Container
Registry via GitHub Actions, tagged `latest` and the short commit SHA:

```
ghcr.io/<owner>/<repo>:latest
```

The image is created **private** on first push — make it public (or configure
pull credentials) from the repo's **Packages** page. Also confirm
**Settings → Actions → General → Workflow permissions** allows the workflow's
`packages: write` scope.

Run it anywhere Docker runs:
```bash
docker run -d --name game-vote \
  -p 8787:8787 \
  -v game-vote-data:/data \
  ghcr.io/<owner>/<repo>:latest
```

Put it behind whatever reverse proxy / TLS you already use, pointing at the
container's port 8787. The `game-vote-data` volume holds `votes.json` — **this
is your entire state; back it up.**

## Notes
- **Config (env vars):** `HOST` (default `0.0.0.0` in the image), `PORT` (default `8787`), `VOTES_FILE` (default `/data/votes.json`).
- **Change games / pros / cons:** edit the `GAMES` list in `index.html`. If you add or rename an id, also update `GAME_IDS` in `server.py` so the backend accepts it.
- **Back up:** copy `votes.json` out of the volume (`docker cp game-vote:/data/votes.json .`). It's the entire state.
- **Identity:** your ballot is keyed by your (normalized) name, so the same name shares one ballot across devices — swipe on desktop, keep going on mobile. Re-using a name re-uses that ballot; the server merges any duplicates by name on startup. It's a friendly-group poll, not a hardened ballot box.
