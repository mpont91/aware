'use client'

import { TrendingUp, TrendingDown } from 'lucide-react'
import { usePnlSummary } from '@/lib/hooks'
import { Skeleton } from '@/components/ui/Loading'

/**
 * Headline P&L. This is a single number people come to read, so it is a hero
 * figure rather than a chart — the trend over time lives in the chart below.
 * Profit and loss carry semantic colour (green / red), which is why the series
 * palette in StrategyPerformance deliberately avoids both.
 */
export function PnlBanner() {
  const { pnl, isLoading } = usePnlSummary()

  const isLive = pnl?.mode === 'LIVE'
  const label = isLive ? 'LIVE TRADING' : 'PAPER TRADING'

  if (isLoading) {
    // Shaped like the banner it replaces — badge, headline figure, and the
    // realized/unrealized pair — so nothing shifts when the numbers arrive.
    return (
      <div className="rounded-2xl bg-slate-900/50 border border-slate-800 p-6">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <Skeleton className="h-5 w-32 mb-3" />
            <Skeleton className="h-10 w-52" />
            <div className="flex gap-6 mt-3">
              <div className="space-y-1">
                <Skeleton className="h-3 w-16" />
                <Skeleton className="h-4 w-20" />
              </div>
              <div className="space-y-1">
                <Skeleton className="h-3 w-16" />
                <Skeleton className="h-4 w-20" />
              </div>
            </div>
          </div>
          <div className="flex gap-8">
            <div className="space-y-2">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-6 w-24" />
            </div>
            <div className="space-y-2">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-6 w-24" />
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (!pnl?.has_data) {
    return (
      <div className="rounded-2xl bg-slate-900/50 border border-slate-800 p-6">
        <span className="px-2 py-0.5 bg-slate-800 rounded text-xs font-medium text-slate-400">
          {label}
        </span>
        <h2 className="text-3xl font-bold text-white mt-3 mb-1">No trades yet</h2>
        <p className="text-slate-400 text-sm">
          P&amp;L appears once a strategy fills its first order. Simulated fills
          need market data flowing first.
        </p>
      </div>
    )
  }

  const up = pnl.total_pnl >= 0
  // Listed in a fixed order, not ranked. There are two strategies and there
  // will stay two, so "best" and "worst" said nothing that the two figures
  // side by side do not say already.
  const strategies = [...pnl.strategies].sort((a, b) =>
    a.strategy.localeCompare(b.strategy)
  )

  const money = (v: number) =>
    `${v >= 0 ? '+' : '−'}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`

  return (
    <div
      className={[
        'relative overflow-hidden rounded-2xl border p-6',
        up
          ? 'bg-gradient-to-r from-emerald-950/60 via-slate-900/60 to-slate-900/40 border-emerald-800/40'
          : 'bg-gradient-to-r from-red-950/60 via-slate-900/60 to-slate-900/40 border-red-800/40',
      ].join(' ')}
    >
      <div className="relative z-10 flex flex-wrap items-end justify-between gap-6">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span
              className={[
                'px-2 py-0.5 rounded text-xs font-medium',
                isLive ? 'bg-red-500/20 text-red-300' : 'bg-slate-700/60 text-slate-300',
              ].join(' ')}
            >
              {label}
            </span>
            <span className="text-xs text-slate-500">
              {pnl.positions} position{pnl.positions === 1 ? '' : 's'}
            </span>
          </div>

          <div className="flex items-baseline gap-3">
            <span
              className={[
                'text-4xl font-bold tabular-nums',
                up ? 'text-emerald-400' : 'text-red-400',
              ].join(' ')}
            >
              {money(pnl.total_pnl)}
            </span>
            <span
              className={[
                'flex items-center gap-1 text-sm font-medium tabular-nums',
                up ? 'text-emerald-400' : 'text-red-400',
              ].join(' ')}
            >
              {up ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
              {pnl.roi_pct >= 0 ? '+' : ''}
              {pnl.roi_pct.toFixed(1)}%
            </span>
          </div>

          {/* The split matters more than the total: realized is settled and
              cannot change, unrealized is a mark-to-market estimate that moves
              until each market resolves. Shown as two labelled figures rather
              than a sentence, so they can be compared at a glance. */}
          <div className="flex gap-6 mt-3">
            <div>
              <p className="text-xs text-slate-500">Realized</p>
              <p
                className={[
                  'text-sm font-semibold tabular-nums',
                  pnl.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400',
                ].join(' ')}
                title="Settled: markets that have resolved. This will not change."
              >
                {money(pnl.realized_pnl)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Unrealized</p>
              <p
                className={[
                  'text-sm font-semibold tabular-nums',
                  pnl.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400',
                ].join(' ')}
                title="Open positions at current market price. Moves until they resolve."
              >
                {money(pnl.unrealized_pnl)}
              </p>
            </div>
          </div>
        </div>

        <div className="flex gap-8">
          {strategies.map((s) => (
            <div key={s.strategy}>
              <p
                className="text-xs text-slate-500 mb-1"
                title={
                  s.strategy === 'UNATTRIBUTED'
                    ? 'Fills with no order record behind them, so they cannot be traced to a strategy. They appear when the engine places an order but cannot write it down — the fill still comes back through the trade feed.'
                    : undefined
                }
              >
                {s.strategy}
              </p>
              <p
                className={[
                  'text-lg font-semibold tabular-nums',
                  s.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400',
                ].join(' ')}
              >
                {money(s.total_pnl)}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
