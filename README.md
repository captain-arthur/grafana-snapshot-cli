# grafana-snapshot-cli

Manual CLI to export Grafana 12 dashboard snapshots (metrics embedded in JSON) and import them back.

## Quick start (Docker)

```bash
docker compose build

export GRAFANA_REPORTS_DIR=~/path/to/grafana_reports
alias grafana-snapshots='docker compose -f /path/to/grafana-snapshot-cli/docker-compose.yaml run --rm snapshot'

# After a load test — capture dashboard for the chosen time range
grafana-snapshots export \
  -u snapshot-demo \
  -f now-1h -t now \
  -n 260604-190102-istio-ingressgateway-baseline-suite \
  -o /reports/devops-gs

# Restore every *.json in a folder into Grafana
grafana-snapshots import -d /reports/devops-gs
```

Environment (optional): `GRAFANA_URL`, `GRAFANA_USER`, `GRAFANA_PASSWORD` (defaults: `http://host.docker.internal:3000`, admin/admin).

## Local run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

export GRAFANA_URL=http://localhost:3000
python cli/snapshot_publish.py export -u snapshot-demo -n my-run -o .
```

## Export flow

1. Open dashboard (`-u`, `-f`, `-t`)
2. Expand collapsed rows, wait for panels to finish loading
3. Publish snapshot via Grafana UI (Playwright)
4. Fail if snapshot has no embedded data (No data)
5. Save `<name>.json` and register snapshot in Grafana under `-n`

## Examples

- `examples/kubernetes/` — minimal Prometheus + Grafana 12.3 for local testing
- `examples/dashboards/` — demo dashboard (`uid: snapshot-demo`)

## License

Apache 2.0 — see [LICENSE](LICENSE).
# grafana-snapshot-cli
