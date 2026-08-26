-- ═══════════════════════════════════════════════════════════════════════════
-- Local IDE user — development only
-- ═══════════════════════════════════════════════════════════════════════════
-- Deliberately kept out of clickhouse/init/, which production mounts whole.
--
-- Two reasons it cannot live there:
--   1. It has no password. In production that would be a way in.
--   2. CREATE USER needs access management rights. Once CLICKHOUSE_PASSWORD
--      is set, the default user loses them, the statement fails with
--      ACCESS_DENIED, and the failure aborts the entire init run: no tables
--      get created and the container exits.
--
-- Mounted only by docker-compose.local.yaml, where ClickHouse runs without a
-- password and its ports are bound to 127.0.0.1.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE USER IF NOT EXISTS intellij IDENTIFIED WITH no_password;
GRANT SELECT ON polybot.* TO intellij;
GRANT SELECT ON system.* TO intellij;
