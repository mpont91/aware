'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  Activity,
  AlertCircle,
  Clock,
  Layers,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import { Skeleton } from '@/components/ui/Loading'
import { apiDate, cn, formatCurrency, formatPercent, getTimeAgo } from '@/lib/utils'
import { api, OpenPosition } from '@/lib/api'

const categories = ['All', 'MIRROR', 'ACTIVE'] as const
type CategoryFilter = (typeof categories)[number]

const categoryLabel: Record<string, string> = {
  MIRROR: 'Copy',
  ACTIVE: 'Active',
}

function PositionsSkeleton() {
  return (
    <div className="divide-y divide-slate-800" aria-hidden="true">
      {Array.from({ length: 10 }).map((_, i) => (
        <div key={i} className="grid grid-cols-12 gap-4 p-4 items-center">
          <div className="col-span-2"><Skeleton className="h-4 w-16" /></div>
          <div className="col-span-3"><Skeleton className="h-4 w-full" /></div>
          <div className="col-span-2"><Skeleton className="h-4 w-16" /></div>
          <div className="col-span-1"><Skeleton className="h-4 w-12" /></div>
          <div className="col-span-2"><Skeleton className="h-4 w-16" /></div>
          <div className="col-span-2"><Skeleton className="h-4 w-20" /></div>
        </div>
      ))}
    </div>
  )
}

export default function PositionsPage() {
  const [positions, setPositions] = useState<OpenPosition[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<CategoryFilter>('All')

  useEffect(() => {
    let cancelled = false

    function load() {
      api
        .getAllPositions()
        .then((data) => { if (!cancelled) { setPositions(data); setError(null) } })
        .catch(() => { if (!cancelled) setError('Failed to load positions') })
    }

    load()
    const interval = setInterval(load, 30000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  const rows = (positions ?? []).filter((p) => filter === 'All' || p.category === filter)

  // Only priced positions count toward the totals — an unpriced one has no
  // value or P&L to add, and treating its missing mark as zero would silently
  // understate the cost still sitting in it.
  const priced = rows.filter((p) => p.unrealized_pnl !== null && p.current_value !== null)
  const totalCost = rows.reduce((sum, p) => sum + p.cost_usd, 0)
  const totalValue = priced.reduce((sum, p) => sum + (p.current_value ?? 0), 0)
  const totalPnl = priced.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0)
  const pricedCost = priced.reduce((sum, p) => sum + p.cost_usd, 0)
  const totalPnlPct = pricedCost ? (totalPnl / pricedCost) * 100 : 0
  const staleCount = rows.length - priced.length

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <Layers className="h-7 w-7 text-aware-400" />
          Open Positions
        </h1>
        <p className="text-slate-400 mt-1">
          Every position every fund holds right now, copy and active strategies together.
          Once a market resolves it drops off this list and its result moves into
          the fund&apos;s realized P&amp;L &mdash; this page only shows what&apos;s still in play.
        </p>
      </div>

      {error && (
        <div className="rounded-xl bg-red-500/10 border border-red-500/30 p-4 flex items-center gap-3">
          <AlertCircle className="h-5 w-5 text-red-400" />
          <p className="text-red-400">{error}</p>
        </div>
      )}

      <div className="flex gap-1 p-1 bg-slate-800/50 rounded-lg w-fit">
        {categories.map((c) => (
          <button
            key={c}
            onClick={() => setFilter(c)}
            className={cn(
              'px-3 py-1.5 text-xs font-medium rounded-md transition-all',
              filter === c ? 'bg-aware-500 text-white' : 'text-slate-400 hover:text-white'
            )}
          >
            {c === 'All' ? 'All' : categoryLabel[c]}
          </button>
        ))}
      </div>

      <div className="rounded-xl bg-slate-900/50 border border-slate-800 overflow-hidden">
        <div className="overflow-x-auto">
          <div className="min-w-[980px]">
            <div className="grid grid-cols-12 gap-4 p-4 bg-slate-800/50 text-xs font-medium text-slate-400 uppercase tracking-wider border-b border-slate-800">
              <div className="col-span-2">Fund</div>
              <div className="col-span-3">Market</div>
              <div className="col-span-2">Bet on</div>
              <div className="col-span-1 text-right">Cost</div>
              <div className="col-span-2 text-right">Entry &rarr; now</div>
              <div className="col-span-1">Opened</div>
              <div className="col-span-1 text-right">P&amp;L</div>
            </div>

            {positions === null ? (
              <PositionsSkeleton />
            ) : rows.length === 0 ? (
              <div className="p-10 text-center">
                <Activity className="h-10 w-10 text-slate-600 mx-auto mb-3" />
                <p className="text-slate-400">No open positions</p>
              </div>
            ) : (
              <div className="divide-y divide-slate-800">
                {rows.map((p) => {
                  const winning = p.unrealized_pnl !== null && p.unrealized_pnl >= 0
                  const isStale = p.mark_status === 'STALE'
                  return (
                    <div
                      key={`${p.fund_id}-${p.token_id}`}
                      className="grid grid-cols-12 gap-4 p-4 items-center hover:bg-slate-800/30 transition-colors"
                    >
                      <div className="col-span-2">
                        <Link
                          href={`/fund?type=${p.fund_id}`}
                          className="text-sm font-medium text-aware-400 hover:text-aware-300"
                        >
                          {p.fund_id}
                        </Link>
                        <p className="text-xs text-slate-500">{categoryLabel[p.category]}</p>
                      </div>

                      <div className="col-span-3 min-w-0">
                        <p className="text-white font-medium truncate" title={p.title}>
                          {p.title || p.market_slug}
                        </p>
                        <p className="text-xs text-slate-500 truncate" title={p.market_slug}>
                          {p.market_slug}
                        </p>
                      </div>

                      <div className="col-span-2 min-w-0">
                        <p className="text-white text-sm truncate" title={p.outcome}>
                          {p.outcome}
                        </p>
                        <p className="text-xs text-slate-500">
                          {p.shares.toLocaleString(undefined, { maximumFractionDigits: 1 })} shares
                        </p>
                      </div>

                      <div className="col-span-1 text-right text-slate-300 font-mono text-sm">
                        {formatCurrency(p.cost_usd)}
                      </div>

                      <div className="col-span-2 text-right font-mono text-sm">
                        <span className="text-slate-400">{(p.avg_entry_price * 100).toFixed(1)}&cent;</span>
                        <span className="text-slate-600 mx-1">&rarr;</span>
                        {isStale ? (
                          <span
                            className="text-slate-500"
                            title={`No trade on this token for ${getTimeAgo(p.last_trade_at)}. Almost always means the market itself stopped trading and is waiting on resolution, not that anything is broken here.`}
                          >
                            no quote
                          </span>
                        ) : (
                          <span className="text-slate-200">{(p.current_price! * 100).toFixed(1)}&cent;</span>
                        )}
                      </div>

                      <div className="col-span-1">
                        <span
                          className="flex items-center gap-1 text-xs text-slate-400"
                          title={p.opened_at ? apiDate(p.opened_at).toLocaleString() : undefined}
                        >
                          <Clock className="h-3 w-3 shrink-0" />
                          {getTimeAgo(p.opened_at)}
                        </span>
                      </div>

                      <div className="col-span-1 text-right">
                        {p.unrealized_pnl === null ? (
                          <span
                            className="text-slate-500 text-xs"
                            title="No fresh quote to value this at &mdash; excluded from the totals below"
                          >
                            unpriced
                          </span>
                        ) : (
                          <div className={cn(
                            'flex items-center justify-end gap-1 font-semibold text-sm',
                            winning ? 'text-green-400' : 'text-red-400'
                          )}>
                            {winning ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
                            <span>
                              {winning ? '+' : '−'}{formatCurrency(Math.abs(p.unrealized_pnl))}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            {rows.length > 0 && (
              <div className="grid grid-cols-12 gap-4 p-4 bg-slate-800/50 border-t border-slate-700 font-semibold">
                <div className="col-span-2 text-slate-300">Totals</div>
                <div className="col-span-5 text-slate-500 text-xs self-center">
                  {rows.length} position{rows.length === 1 ? '' : 's'}
                  {staleCount > 0 && ` · ${staleCount} without a fresh quote, excluded from P&L`}
                </div>
                <div className="col-span-1 text-right text-slate-300 font-mono text-sm">
                  {formatCurrency(totalCost)}
                </div>
                <div className="col-span-2 text-right text-slate-400 font-mono text-sm self-center">
                  {formatCurrency(totalValue)} now
                </div>
                <div className="col-span-2 text-right">
                  <span className={cn(totalPnl >= 0 ? 'text-green-400' : 'text-red-400')}>
                    {totalPnl >= 0 ? '+' : '−'}{formatCurrency(Math.abs(totalPnl))}
                  </span>
                  <span className="text-xs text-slate-500 ml-1">
                    ({formatPercent(totalPnlPct)})
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="rounded-xl bg-slate-800/20 border border-slate-800 p-4 text-sm text-slate-400 space-y-2">
        <p>
          <span className="text-slate-300 font-medium">&ldquo;no quote&rdquo; / &ldquo;unpriced&rdquo;</span> means
          this token hasn&apos;t printed a trade in the last ~15 minutes. Almost always that&apos;s because the
          market itself has stopped trading &mdash; a match ended, a 15-minute crypto window closed &mdash; and
          it&apos;s sitting there waiting for a resolution, not because anything here is broken.
        </p>
        <p>
          We don&apos;t currently have reliable market close/event-time data wired in (the Gamma market
          metadata feed isn&apos;t being ingested), so there&apos;s no &ldquo;closes in&rdquo; column yet. &ldquo;Opened&rdquo;
          is when we entered the position; a closed/resolved market simply disappears from this list.
        </p>
      </div>
    </div>
  )
}
