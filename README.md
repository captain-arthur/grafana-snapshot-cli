# grafana-snapshot-cli

Export Grafana 12 dashboard snapshots (metrics embedded in JSON) and import them back.

## Local (uv)

Requires [uv](https://docs.astral.sh/uv/).

```bash
cd ~/Documents/github/grafana-snapshot-cli
uv sync
uv run playwright install chromium
```

Set Grafana credentials, then run:

```bash
export GRAFANA_URL=https://your-grafana.example.com
export GRAFANA_USER=admin
export GRAFANA_PASSWORD=secret

uv run grafana-snapshots --version

uv run grafana-snapshots export \
  -u <dashboard-uid> \
  -f now-1h \
  -t now \
  -n <snapshot-name> \
  -o ./reports/<subdir>

uv run grafana-snapshots import -d ./reports/<subdir>
```

| Item | Meaning |
|------|---------|
| `-u` | Dashboard UID |
| `-f` / `-t` | Time range |
| `-n` | Snapshot name (Grafana title + `<name>.json`) |
| `-o` | Output directory on the host |

Grafana chart/env: `GF_SERVER_ROOT_URL=%(protocol)s://%(domain)s:%(http_port)s/`

## Docker

```bash
docker build -t grafana-snapshots:v0.1.0 .
```

Edit `docker-compose.yaml` `environment` and volume, then:

```bash
alias grafana-snapshots='docker compose -f ~/Documents/github/grafana-snapshot-cli/docker-compose.yaml run --rm grafana-snapshots'

grafana-snapshots export \
  -u <dashboard-uid> \
  -f now-1h \
  -t now \
  -n <snapshot-name> \
  -o /reports/<subdir>

grafana-snapshots import -d /reports/<subdir>
```

Paths under `-o` / `-d` are inside the container (`./reports` on the host via volume).

## License

Apache 2.0 — see [LICENSE](LICENSE).
