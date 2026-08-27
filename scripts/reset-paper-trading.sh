#!/usr/bin/env bash
#
# Wipe the paper trading record and start the book from zero.
#
# Clears only what WE produced by trading: simulated fills, fund orders,
# strategy orders, order lifecycle and every P&L snapshot derived from them.
# After this the paper bankroll reads as the untouched starting capital.
#
# It does NOT touch observed market data or trader analytics — global trades,
# smart money scores, PSI indices, market resolutions, classifications, alerts.
# Those took days to accumulate and say nothing about our own positions.
#
# The strategy and executor services are stopped first so nothing lands
# mid-wipe, and restarted after: the simulator holds its positions in memory,
# so it has to come back up empty for its state to match the tables.
#
# Usage:  ./scripts/reset-paper-trading.sh [--yes]

set -euo pipefail

CH_CONTAINER="${CH_CONTAINER:-aware-clickhouse}"
DB="${CLICKHOUSE_DATABASE:-polybot}"

TABLES=(
  # Simulated fills — the durable record every P&L figure is built from
  user_trades
  # Orders each engine placed
  aware_fund_executions
  strategy_gabagool_orders
  # Order lifecycle
  executor_order_limit
  executor_order_market
  executor_order_cancel
  executor_order_status
  # P&L snapshots derived from the above
  aware_strategy_pnl
  aware_strategy_pnl_positions
  aware_fund_pnl
  # Legacy fund bookkeeping, unused but wiped so nothing stale survives
  aware_fund_positions
  aware_fund_trades
  aware_fund_nav
  aware_fund_nav_history
)

ch() { docker exec -i "$CH_CONTAINER" clickhouse-client -d "$DB" -q "$1"; }

echo "About to clear the paper trading record:"
total=0
for t in "${TABLES[@]}"; do
  n=$(ch "SELECT count() FROM $t" 2>/dev/null || echo "n/a")
  printf '  %-32s %s rows\n' "$t" "$n"
  [[ "$n" =~ ^[0-9]+$ ]] && total=$((total + n))
done
echo "  ---"
printf '  %-32s %s rows\n' "TOTAL" "$total"
echo
echo "Left untouched: aware_global_trades, aware_smart_money_scores,"
echo "aware_psi_index, aware_market_resolutions, aware_market_classifications,"
echo "aware_alerts, aware_trader_* — observed data, not our positions."
echo

if [[ "${1:-}" != "--yes" ]]; then
  read -r -p "Type RESET to proceed: " answer
  [[ "$answer" == "RESET" ]] || { echo "Aborted."; exit 1; }
fi

echo "Stopping the trading services..."
docker stop aware-strategy aware-executor >/dev/null

echo "Truncating..."
for t in "${TABLES[@]}"; do
  ch "TRUNCATE TABLE IF EXISTS $t" && echo "  $t"
done

echo "Starting the trading services..."
docker start aware-executor aware-strategy >/dev/null

echo
echo "Done. The book is empty and the paper bankroll reads as starting capital."
echo "P&L figures stay blank until the analytics cycle runs (hourly, or run"
echo "run_all.py by hand to see them sooner)."
