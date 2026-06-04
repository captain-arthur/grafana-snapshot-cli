# grafana-snapshot-cli

Export Grafana 12 dashboard snapshots (metrics embedded in JSON) and import them back.

## 1. Build image

```bash
cd ~/Documents/github/grafana-snapshot-cli
docker build -t grafana-snapshots:v0.1.0 .
```

## 2. Configure `docker-compose.yaml`

Edit `environment` and the volume if needed:

```yaml
environment:
  GRAFANA_URL: https://your-grafana.example.com
  GRAFANA_USER: admin
  GRAFANA_PASSWORD: secret
volumes:
  - ./reports:/reports
```

## 3. Alias

```bash
alias grafana-snapshots='docker compose -f ~/Documents/github/grafana-snapshot-cli/docker-compose.yaml run --rm grafana-snapshots'
```

## 4. Run

```bash
grafana-snapshots --version

grafana-snapshots export \
  -u <dashboard-uid> \
  -f now-1h \
  -t now \
  -n <snapshot-name> \
  -o /reports/<subdir>

grafana-snapshots import -d /reports/<subdir>
```

| Item | Meaning |
|------|---------|
| `-u` | Dashboard UID |
| `-f` / `-t` | Time range |
| `-n` | Snapshot name (Grafana title + `<name>.json`) |
| `-o` | Path under `/reports` in the container → `./reports/<subdir>/` on the host |

Grafana chart/env: `GF_SERVER_ROOT_URL=%(protocol)s://%(domain)s:%(http_port)s/`

## License

Apache 2.0 — see [LICENSE](LICENSE).
