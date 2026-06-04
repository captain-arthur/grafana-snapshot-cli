# grafana-snapshot-cli

Export Grafana 12 dashboard snapshots (metrics embedded in JSON) and import them back.

## Docker (recommended)

Use **docker compose** so Grafana URL, credentials, and dashboard UID come from `docker-compose.yaml`.  
Do **not** use `uv run` for this path — `uv run` reads `cli/config.py` defaults on the host, not compose `environment`.

### 1. Build the image

From the repo root:

```bash
docker build -t grafana-snapshots:v0.1.0 .
```

Rebuild after code changes.

### 2. Configure `docker-compose.yaml`

Edit `environment` for your Grafana:

| Variable | Example | Meaning |
|----------|---------|---------|
| `GRAFANA_URL` | `http://host.docker.internal:3000` | Grafana base URL **as seen from the container** |
| `GRAFANA_USER` | `admin` | Login user |
| `GRAFANA_PASSWORD` | `admin` | Login password |
| `GRAFANA_DASHBOARD_UID` | `snapshot-demo` | Dashboard UID to open before snapshot |

- **Grafana on the host (Docker Desktop):** `http://host.docker.internal:3000`
- **Grafana in Kubernetes / another host:** use an URL reachable from the container (not `localhost` on the host).

Confirm in a browser: `{GRAFANA_URL}/d/{GRAFANA_DASHBOARD_UID}` loads the dashboard and shows **Share**.

`volumes` maps host `./reports` → container `/reports` (JSON files persist on the host).

### 3. Export

```bash
docker compose run --rm grafana-snapshots \
  export -n <snapshot-name> -f now-1h -t now -d /reports/<subdir>
```

Output on the host: `./reports/<subdir>/<snapshot-name>.json`

### 4. Import

```bash
docker compose run --rm grafana-snapshots \
  import -d /reports/<subdir>
```

### Optional alias

```bash
alias grafana-snapshots='docker compose run --rm grafana-snapshots'

grafana-snapshots export -n weekly -f now-1h -t now -d /reports/team-a
grafana-snapshots import -d /reports/team-a
```

### `uv run` vs Docker

| | `uv run grafana-snapshots` | `docker compose run ... grafana-snapshots` |
|--|---------------------------|------------------------------------------|
| Config | `cli/config.py` + host `export` | `docker-compose.yaml` `environment` |
| Reports path `-d` | Host path, e.g. `./reports/team-a` | Container path, e.g. `/reports/team-a` → host `./reports/team-a` |
| Playwright | Host Chromium | Image Chromium |

Grafana chart/env: `GF_SERVER_ROOT_URL=%(protocol)s://%(domain)s:%(http_port)s/`

---

## Local (uv)

For development on the host without Docker.

Requires [uv](https://docs.astral.sh/uv/).

```bash
cd ~/Documents/github/grafana-snapshot-cli
uv sync
uv run playwright install chromium
```

Set env vars or edit `cli/config.py` (`GRAFANA_URL`, `GRAFANA_DASHBOARD_UID`, etc.):

```bash
export GRAFANA_URL=https://your-grafana.example.com
export GRAFANA_USER=admin
export GRAFANA_PASSWORD=secret
export GRAFANA_DASHBOARD_UID=your-dashboard-uid

uv run grafana-snapshots export \
  -n <snapshot-name> \
  -f now-1h \
  -t now \
  -d ./reports/<subdir>

uv run grafana-snapshots import -d ./reports/<subdir>
```

| Item | Meaning |
|------|---------|
| `GRAFANA_DASHBOARD_UID` | Dashboard UID (env or `cli/config.py` default) |
| `-f` / `-t` | Time range |
| `-n` | Snapshot name (Grafana title + `<name>.json`) |
| `-d` / `--directory` | Reports directory on the **host** |

## License

Apache 2.0 — see [LICENSE](LICENSE).
