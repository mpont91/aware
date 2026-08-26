'use client'

import { TrendingUp, TrendingDown } from 'lucide-react'
import { usePnlSummary } from '@/lib/hooks'

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
    return (
      <div className="rounded-2xl bg-slate-900/50 border border-slate-800 p-6">
        <div className="h-24 flex items-center">
          <p className="text-slate-500">Loading P&amp;L…</p>
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
  const best = [...pnl.strategies].sort((a, b) => b.total_pnl - a.total_pnl)[0]
  const worst = [...pnl.strategies].sort((a, b) => a.total_pnl - b.total_pnl)[0]
  const showWorst = worst && best && worst.strategy !== best.strategy

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

          <p className="text-slate-400 text-sm mt-1">
            {/* Realised is settled and final; unrealised still moves. */}
            <span className="tabular-nums">{money(pnl.realized_pnl)}</span> realised
            {' · '}
            <span className="tabular-nums">{money(pnl.unrealized_pnl)}</span> open
          </p>
        </div>

        <div className="flex gap-8">
          {best && (
            <div>
              <p className="text-xs text-slate-500 mb-1">Best strategy</p>
              <p className="text-sm font-medium text-white">{best.strategy}</p>
              <p
                className={[
                  'text-lg font-semibold tabular-nums',
                  best.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400',
                ].join(' ')}
              >
                {money(best.total_pnl)}
              </p>
            </div>
          )}
          {showWorst && (
            <div>
              <p className="text-xs text-slate-500 mb-1">Worst strategy</p>
              <p className="text-sm font-medium text-white">{worst.strategy}</p>
              <p
                className={[
                  'text-lg font-semibold tabular-nums',
                  worst.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400',
                ].join(' ')}
              >
                {money(worst.total_pnl)}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
