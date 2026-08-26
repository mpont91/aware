# Deploying AWARE behind Caddy

Runs the stack in production on a single server, with the dashboard and API
served over HTTPS behind HTTP basic auth. Assumes Caddy is already installed on
the host and owns ports 80/443.

The bundled nginx service is not used. `docker-compose.caddy.yaml` parks it
behind an unused profile so it never starts.

## What ends up exposed

Only Caddy listens publicly. Every container binds to `127.0.0.1`, and
ClickHouse and Redpanda publish no host ports at all.

Caddy forwards a single port. The dashboard rewrites `/api/*` to the API over
the compose network itself, so the API needs no route of its own.

| | reachable from internet |
|---|---|
| dashboard (`/`) | yes, behind basic auth |
| AWARE API (`/api/*`, through the dashboard) | yes, behind basic auth |
| Grafana, Prometheus | no — SSH tunnel |
| Java services, ClickHouse, Redpanda | no |

## 1. Clone and configure

```bash
sudo mkdir -p /opt/aware && sudo chown "$USER" /opt/aware
git clone git@github.com:mpont91/aware.git /opt/aware
cd /opt/aware
```

ClickHouse applies `analytics-service/clickhouse/init/*.sql` by itself on its
first start, so there is no schema step to run. It only happens while the data
volume is empty; to reapply later, drop the volume or run the statements by
hand.

Sizing: the stack idles around **5 GB of RAM** and grows with ingested data.
8 GB is the practical floor, 16 GB comfortable. ClickHouse and Redpanda are
the heavy ones.

Create `.env` in the repo root (`/opt/aware/.env`) — both the Makefile and the
production compose files read it from there:

```bash
SERVER_USER=tu_usuario
SERVER_IP=1.2.3.4
PROJECT_PATH=/opt/aware

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

`SERVER_*` and `PROJECT_PATH` are only read by `make deploy`/`make ssh` from
your own machine; they do no harm in the server's copy.

## 2. Point the domain at the server

An `A` record for your domain to the server's public IP. Caddy needs this
resolving before it can get a certificate. The domain is configured only in the
Caddyfile — nothing in the stack needs to know its own hostname.

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

	reverse_proxy localhost:3000
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
cd /opt/aware
make prod-up
```

That runs the compose files from the repo root so `.env` is picked up, builds
the images, and prunes the old ones. `--build` matters on the first run and
after pulling changes. Changing the domain never needs a rebuild: it lives in
the Caddyfile, and the dashboard calls its own origin.

## 5. Verify

```bash
# should be 401 without credentials
curl -o /dev/null -s -w '%{http_code}\n' https://aware.tudominio.com/api/leaderboard

# should be 200 with them, both for pages and for the API
curl -o /dev/null -s -w '%{http_code}\n' -u tu_usuario https://aware.tudominio.com/
curl -o /dev/null -s -w '%{http_code}\n' -u tu_usuario https://aware.tudominio.com/api/leaderboard

# nothing but 80/443 should answer from outside
nmap -Pn aware.tudominio.com
```

Then open the dashboard, enter the credentials, and check that the leaderboard
loads. If the pages render but the data does not, the web image was built
without `API_INTERNAL_URL`: `next.config.js` resolves its rewrite target at
build time, so the proxy would be pointing at `localhost:8000` inside the
container. Rebuild with `--build`.

## Reaching Grafana

Not published on purpose. Use a tunnel:

```bash
ssh -L 3001:127.0.0.1:3001 user@server
```

Then open `http://localhost:3001`.

## Updating

From your laptop, one command:

```bash
make deploy
```

It SSHes in, pulls and restarts (`make prod-up` on the server). Needs
`SERVER_USER`, `SERVER_IP` and `PROJECT_PATH` in your local `.env`.

`make ssh` drops you into a shell in the project directory on the server.
Once there, `make prod-logs`, `make prod-status` and `make prod-down` work.

## Notes

- **Basic auth is only as safe as the transport.** Credentials go in a header on
  every request, base64 encoded, which is fine over HTTPS and readable over
  plain HTTP. Caddy redirects to HTTPS by default; do not disable that.
- **The API has two write endpoints**, `/api/fund/activate` and
  `/api/fund/pause`. They sit behind the same basic auth as everything else,
  which is the only thing stopping a stranger from pausing your funds.
- **`ALLOWED_ORIGINS` in `main.py` is hardcoded to localhost.** It does not
  affect this setup: the browser only ever talks to the dashboard's origin, so
  no CORS check happens. It would matter if you published the API separately.
- **Both `NEXT_PUBLIC_API_URL` and `API_INTERNAL_URL` are build-time values**
  for the web image. Next.js inlines the first into the client bundle and
  evaluates the second while resolving `next.config.js` rewrites. Setting
  either only in `environment:` has no effect.
