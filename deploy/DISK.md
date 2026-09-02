# Disk budget

The host has 79 GB. On 2 September 2026 it hit 100% and took the stack down:
ClickHouse could not write a temp file, Redpanda could not write a segment and
restarted 238 times, and the ingestor went unhealthy behind it.

Six days earlier the growth had been measured and capped (`302_retention.sql`,
commit `3a36d1f`): 533 MB/day against 25 GB free, "about seven weeks". The
caps worked — the tables they covered are still small. The estimate was wrong
because it was taken from **inside the application database**. Sorted by size,
the disk actually looked like this:

| | |
|---|---|
| ClickHouse's own `system.*` log tables | 22.8 GB |
| Redpanda, seven days of consumed events | 16 GB |
| Docker build cache | 16.5 GB |
| Docker images | 13.4 GB |
| Container logs, never rotated | ~1 GB |
| **Application data — the part that was measured** | **3.3 GB** |

The measured part was 4% of the problem. **The lesson is the method: measure
the disk, not the database.** `df -h /` and `docker system df` first, table
sizes second.

## What holds what, and what stops it

| Component | Ceiling | Enforced by |
|---|---|---|
| ClickHouse firehoses (`analytics_events`, `market_ws_tob`, order lifecycle) | ~2.7 GB | 7-day TTL — `init/302_retention.sql` |
| ClickHouse per-position P&L snapshots | ~75 MB | 7-day TTL — same file |
| ClickHouse `system.*` telemetry | ~1 GB | 3-day TTL, two tables off — `config.d/logging.xml`, `users.d/query-logging.xml` |
| ClickHouse accumulated observations | **none — see below** | deliberate |
| Redpanda | 2 GB | `retention_bytes`, applied by `make prod-up` |
| Docker images | ~14 GB | `docker image prune` on deploy |
| Docker build cache | 5 GB | `--max-used-space` on deploy |
| Container logs | 1.65 GB | `max-size: 50m` × 3 × 11 services |
| Prometheus | 1 GB | `retention.size` (a time limit alone is not a disk limit) |
| Grafana | <100 MB | — |
| journald + `/var/log` | 7.9 GB | journald's default 10%-of-filesystem cap |

Everything above is bounded. Total ceiling is roughly 35 GB against 79 GB.

## The one thing that grows forever

`aware_global_trades` — the Polymarket trades the project observes — is the
data the whole product accumulates, and it is deliberately left uncapped:

    116,000 rows/day x 408 B  =  47.6 MB/day  =  17.5 GB/year

With 46 GB free that is about **two and a half years**. It is the only
unbounded thing on this host, and it is worth knowing rather than fixing: the
day it matters, the fix is to keep full detail for 90 days and aggregate
older trades per trader per month, not to throw the history away.

## The alarm

`notifications/ops.py` warns at 85% used, reading `system.disks` — ClickHouse
sits on the same filesystem as everything else, so it sees the host's free
space without extra plumbing. During the outage the alerts reported the
failing job and never the reason; this is the check that was missing.

## When it happens anyway

    make purge-ch-logs    # reclaims ClickHouse's log tables from a laptop

Those hold nothing but the server's own logs and query traces. Trading data
lives in the `polybot` database and is untouched.
