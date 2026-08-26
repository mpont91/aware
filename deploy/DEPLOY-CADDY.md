# Deploying AWARE behind Caddy

Runs the stack in production on a single server, with the dashboard and API
served over HTTPS behind HTTP basic auth. Assumes Caddy is already installed on
the host and owns ports 80/443.

The bundled nginx service is not used. `docker-compose.caddy.yaml` parks it
behind an unused profile so it never starts.

## What ends up exposed

Only Caddy listens publicly. Every container binds to `127.0.0.1`, and
ClickHouse and Redpanda publish no host ports at all.

| | reachable from internet |
|---|---|
| dashboard (`/`) | yes, behind basic auth |
| AWARE API (`/api/*`) | yes, behind basic auth |
| Grafana, Prometheus | no — SSH tunnel |
| Java services, ClickHouse, Redpanda | no |

## 1. Clone and configure

```bash
sudo mkdir -p /opt/aware && sudo chown "$USER" /opt/aware
git clone git@github.com:mpont91/aware.git /opt/aware
cd /opt/aware/deploy
```

Create `/opt/aware/deploy/.env`:

```bash
AWARE_DOMAIN=aware.tudominio.com

# Trading stays simulated. Switch to LIVE only after the P&L numbers in
# aware_strategy_pnl justify it.
HFT_MODE=PAPER

CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=<long random string>

GRAFANA_USER=admin
GRAFANA_PASSWORD=<long random string>

# Required by the compose file even in PAPER mode. Leave as placeholders
# until you actually go live; nothing reads them for simulated orders.
POLYMARKET_API_KEY=unused-in-paper
POLYMARKET_API_SECRET=unused-in-paper
POLYMARKET_PASSPHRASE=unused-in-paper
POLYMARKET_PRIVATE_KEY=unused-in-paper
```

```bash
chmod 600 .env
```

## 2. Point the domain at the server

An `A` record for `AWARE_DOMAIN` to the server's public IP. Caddy needs this
resolving before it can get a certificate.

## 3. Configure Caddy

Generate a password hash — never store the plaintext:

```bash
caddy hash-password
```

Add to `/etc/caddy/Caddyfile` (or import `deploy/caddy/Caddyfile`):

```caddy
aware.tudominio.com {
	encode gzip

	basic_auth {
		tu_usuario $2a$14$...el.hash.que.acabas.de.generar...
	}

	handle /api/* {
		reverse_proxy 127.0.0.1:8000
	}

	handle {
		reverse_proxy 127.0.0.1:3000
	}
}
```

On Caddy older than 2.8 the directive is `basicauth`, not `basic_auth`.

```bash
caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy requests the certificate on first request. No certbot, no renewal cron.

## 4. Start the stack

```bash
cd /opt/aware/deploy
docker compose -f docker-compose.prod.yaml -f docker-compose.caddy.yaml up -d --build
```

The `--build` matters on the first run and after any change to `AWARE_DOMAIN`:
`NEXT_PUBLIC_API_URL` is compiled into the dashboard's client bundle, so
changing the domain means rebuilding the web image, not just restarting it.

## 5. Apply the ClickHouse schema

```bash
cd /opt/aware
scripts/clickhouse/apply-init.sh
```

## 6. Verify

```bash
# should be 401 without credentials
curl -o /dev/null -s -w '%{http_code}\n' https://aware.tudominio.com/api/leaderboard

# should be 200 with them
curl -o /dev/null -s -w '%{http_code}\n' -u tu_usuario https://aware.tudominio.com/api/leaderboard

# nothing but 80/443 should answer from outside
nmap -Pn aware.tudominio.com
```

Then open the dashboard, enter the credentials, and check that the leaderboard
loads. If the page renders but the data does not, the client bundle was built
with the wrong URL — rebuild with `--build`.

## Reaching Grafana

Not published on purpose. Use a tunnel:

```bash
ssh -L 3001:127.0.0.1:3001 user@server
```

Then open `http://localhost:3001`.

## Updating

```bash
cd /opt/aware
git pull origin main
cd deploy
docker compose -f docker-compose.prod.yaml -f docker-compose.caddy.yaml up -d --build
```

## Notes

- **Basic auth is only as safe as the transport.** Credentials go in a header on
  every request, base64 encoded, which is fine over HTTPS and readable over
  plain HTTP. Caddy redirects to HTTPS by default; do not disable that.
- **The API has two write endpoints**, `/api/fund/activate` and
  `/api/fund/pause`. They sit behind the same basic auth as everything else,
  which is the only thing stopping a stranger from pausing your funds.
- **`ALLOWED_ORIGINS` in `main.py` is hardcoded to localhost.** It does not
  affect this setup because the dashboard and API share an origin, so no CORS
  check happens. It would matter if you ever served them from different hosts.
