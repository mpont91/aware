# Deploying AWARE

Runs the whole stack on a dedicated server, served over HTTPS behind HTTP basic
auth. Everything is containerised, including the reverse proxy: nothing has to
be installed or configured on the host beyond Docker.

Caddy obtains and renews the TLS certificate itself, so there is no certbot
step and no renewal to schedule. The domain comes from `.env` rather than being
baked into a config file.

Assumes the server is dedicated to AWARE — the Caddy container claims ports 80
and 443. To run alongside an existing proxy, see [Sharing a server](#sharing-a-server).

Caddy is built from `deploy/Dockerfile.caddy` with the `caddy-ratelimit`
plugin compiled in, which is the one thing the stock image lacks and the
previous nginx setup provided.

## Requirements

The stack idles around **4 GB of RAM** and grows with ingested data. 8 GB is a
sensible floor; ClickHouse and Redpanda are the heavy ones.

Disk: ClickHouse uses roughly **1 GB per day** of continuous ingestion, so size
it for how much history you want. 60 GB is a reasonable start.

## What ends up exposed

Only the Caddy container publishes to the internet. Every other service binds
to `127.0.0.1`, and Caddy reaches them over the compose network.

| | reachable from internet |
|---|---|
| dashboard (`/`) | yes, behind basic auth |
| AWARE API (`/api/*`, through the dashboard) | yes, behind basic auth |
| `/health` | yes, unauthenticated, returns `OK` |
| Grafana, Prometheus | no — SSH tunnel |
| Java services, ClickHouse, Redpanda | no |

Rate limits are per client IP: 10 requests/second on `/api/*`, 30 elsewhere.
Exceeding them returns 429.

## 1. Point the domain at the server

An `A` record to the server's public IP. Caddy needs it resolving before it can
obtain a certificate.

## 2. Clone

```bash
sudo mkdir -p /opt/aware && sudo chown "$USER" /opt/aware
git clone git@github.com:mpont91/aware.git /opt/aware
cd /opt/aware
```

## 3. Configure

Generate a password hash:

```bash
docker run --rm caddy:2-alpine caddy hash-password
```

Create `.env` in the repo root — the Makefile and the compose files both read
it from there:

```bash
AWARE_DOMAIN=aware.tudominio.com
AWARE_USER=tu_usuario
AWARE_PASSWORD_HASH='$2a$14$...el.hash.generado...'

# Trading stays simulated. Switch to LIVE only when the numbers in
# aware_strategy_pnl justify it.
HFT_MODE=PAPER

CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=<openssl rand -base64 32>

GRAFANA_USER=admin
GRAFANA_PASSWORD=<openssl rand -base64 32>

# Required by the compose file even in PAPER mode; nothing reads them for
# simulated orders.
POLYMARKET_API_KEY=unused-in-paper
POLYMARKET_API_SECRET=unused-in-paper
POLYMARKET_PASSPHRASE=unused-in-paper
POLYMARKET_PRIVATE_KEY=unused-in-paper
```

```bash
chmod 600 .env
```

**Keep the single quotes around the hash.** Without them compose reads the `$`
segments of a bcrypt hash as variables and truncates it silently, and every
login then fails.

## 4. Deploy

```bash
make prod-up
```

That is the whole deployment. It builds the images and starts everything; Caddy
requests the certificate on the first request to your domain.

ClickHouse applies `analytics-service/clickhouse/init/*.sql` by itself on first
start, so there is no schema step. It only happens while the data volume is
empty.

## 5. Verify

```bash
# 401 without credentials
curl -o /dev/null -s -w '%{http_code}\n' https://aware.tudominio.com/

# 200 with them, for both pages and API
curl -o /dev/null -s -w '%{http_code}\n' -u tu_usuario https://aware.tudominio.com/
curl -o /dev/null -s -w '%{http_code}\n' -u tu_usuario https://aware.tudominio.com/api/leaderboard

# only 80 and 443 should answer from outside
nmap -Pn aware.tudominio.com
```

The dashboard starts empty and fills over the following hours as data arrives.
Follow it with `make prod-logs SERVICE=ingestor`.

## Updating

From your own machine:

```bash
make deploy
```

SSHes in, pulls, rebuilds and restarts. Needs `SERVER_USER`, `SERVER_IP` and
`PROJECT_PATH` in your local `.env`.

`make ssh` opens a shell in the project directory on the server, where
`make prod-logs`, `make prod-status` and `make prod-down` are available.

## Reaching Grafana

Not published on purpose. Use a tunnel:

```bash
ssh -L 3001:127.0.0.1:3001 user@server
```

Then open `http://localhost:3001`.

## Sharing a server

If something else already owns 80/443, drop the Caddy overlay and let the
existing proxy forward to `WEB_PORT`:

Give the `caddy` service a profile so it does not start, and point the existing
proxy at `WEB_PORT`. A single route to `localhost:3000` is enough — the
dashboard reaches the API itself. You lose the rate limiting, which lives in
the Caddy config, so configure it in that proxy instead.

## Notes

- **Basic auth is only as safe as the transport.** Credentials travel in a
  header on every request, base64 encoded: fine over HTTPS, readable over plain
  HTTP. Caddy redirects to HTTPS by default; leave it that way.
- **The API has two write endpoints**, `/api/fund/activate` and
  `/api/fund/pause`, behind the same basic auth as everything else.
- **Certificates live in the `caddy_data` volume.** Do not prune it, or Caddy
  re-requests certificates on every recreate and hits Let's Encrypt rate limits.
- **`NEXT_PUBLIC_API_URL` and `API_INTERNAL_URL` are build-time values.**
  Next.js inlines the first into the client bundle and resolves the second while
  evaluating `next.config.js` rewrites. Setting either only in `environment:`
  has no effect.
