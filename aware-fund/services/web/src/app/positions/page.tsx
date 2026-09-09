'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Layers,
  TrendingDown,
  TrendingUp,
  XCircle,
} from 'lucide-react'
import { Skeleton } from '@/components/ui/Loading'
import { apiDate, cn, formatCurrency, formatPercent, getTimeAgo } from '@/lib/utils'
import { api, ClosedPosition, ClosedPositionsResponse, OpenPosition, OpenPositionsResponse } from '@/lib/api'

const categories = ['All', 'MIRROR', 'ACTIVE'] as const
type CategoryFilter = (typeof categories)[number]

const categoryLabel: Record<string, string> = {
  MIRROR: 'Copy',
  ACTIVE: 'Active',
}

const PAGE_SIZE = 50

function TableSkeleton({ cols }: { cols: number[] }) {
  return (
    <div className="divide-y divide-slate-800" aria-hidden="true">
      {Array.from({ length: 10 }).map((_, i) => (
        <div key={i} className="grid grid-cols-12 gap-4 p-4 items-center">
          {cols.map((span, j) => (
            <div key={j} className={`col-span-${span}`}><Skeleton className="h-4 w-full" /></div>
          ))}
        </div>
      ))}
    </div>
  )
}

function CategoryFilterBar({ value, onChange }: { value: CategoryFilter; onChange: (c: CategoryFilter) => void }) {
  return (
    <div className="flex gap-1 p-1 bg-slate-800/50 rounded-lg w-fit">
      {categories.map((c) => (
        <button
          key={c}
          onClick={() => onChange(c)}
          className={cn(
            'px-3 py-1.5 text-xs font-medium rounded-md transition-all',
            value === c ? 'bg-aware-500 text-white' : 'text-slate-400 hover:text-white'
          )}
        >
          {c === 'All' ? 'All' : categoryLabel[c]}
        </button>
      ))}
    </div>
  )
}

function PaginationBar({
  total, offset, pageSize, onOffsetChange,
}: { total: number; offset: number; pageSize: number; onOffsetChange: (offset: number) => void }) {
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + pageSize, total)
  return (
    <div className="flex items-center gap-3 text-sm text-slate-400">
      <span>{total === 0 ? 'No results' : `${from}–${to} of ${total}`}</span>
      <div className="flex gap-1">
        <button
          onClick={() => onOffsetChange(Math.max(0, offset - pageSize))}
          disabled={offset === 0}
          className="p-1.5 rounded-lg bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed hover:bg-slate-700"
          aria-label="Previous page"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <button
          onClick={() => onOffsetChange(offset + pageSize)}
          disabled={offset + pageSize >= total}
          className="p-1.5 rounded-lg bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed hover:bg-slate-700"
          aria-label="Next page"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

function OpenPositionsView() {
  const [filter, setFilter] = useState<CategoryFilter>('All')
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState<OpenPositionsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Changing the category filter without resetting the page could land you
  // past the end of a much shorter filtered list.
  useEffect(() => { setOffset(0) }, [filter])

  useEffect(() => {
    let cancelled = false
    const category = filter === 'All' ? 'ALL' : filter
    function load() {
      api
        .getAllPositions(category, PAGE_SIZE, offset)
        .then((res) => { if (!cancelled) { setData(res); setError(null) } })
        .catch(() => { if (!cancelled) setError('Failed to load positions') })
    }
    load()
    const interval = setInterval(load, 30000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [filter, offset])

  const rows = data?.items ?? []
  const total = data?.total ?? 0
  const priced = rows.filter((p) => p.unrealized_pnl !== null && p.current_value !== null)
  const totalCost = rows.reduce((sum, p) => sum + p.cost_usd, 0)
  const totalValue = priced.reduce((sum, p) => sum + (p.current_value ?? 0), 0)
  const totalPnl = priced.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0)
  const pricedCost = priced.reduce((sum, p) => sum + p.cost_usd, 0)
  const totalPnlPct = pricedCost ? (totalPnl / pricedCost) * 100 : 0
  const staleCount = rows.length - priced.length

  return (
    <>
      {error && (
        <div className="rounded-xl bg-red-500/10 border border-red-500/30 p-4 flex items-center gap-3 mb-4">
          <AlertCircle className="h-5 w-5 text-red-400" />
          <p className="text-red-400">{error}</p>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <CategoryFilterBar value={filter} onChange={setFilter} />
        {data && <PaginationBar total={total} offset={offset} pageSize={PAGE_SIZE} onOffsetChange={setOffset} />}
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

            {data === null ? (
              <TableSkeleton cols={[2, 3, 2, 1, 2, 1, 1]} />
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
                            title="No fresh quote to value this at — excluded from the totals below"
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
                <div className="col-span-2 text-slate-300">This page</div>
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

      {total > rows.length && (
        <p className="text-xs text-slate-500 mt-3 text-center">
          Totals above are for this page only, not all {total.toLocaleString()} open positions.
        </p>
      )}

      <div className="rounded-xl bg-slate-800/20 border border-slate-800 p-4 text-sm text-slate-400 space-y-2 mt-6">
        <p>
          <span className="text-slate-300 font-medium">&ldquo;no quote&rdquo; / &ldquo;unpriced&rdquo;</span> means
          this token hasn&apos;t printed a trade in the last ~15 minutes. Almost always that&apos;s because the
          market itself has stopped trading &mdash; a match ended, a 15-minute crypto window closed &mdash; and
          it&apos;s sitting there waiting for a resolution, not because anything here is broken.
        </p>
        <p>
          We don&apos;t currently have reliable market close/event-time data wired in (the Gamma market
          metadata feed isn&apos;t being ingested), so there&apos;s no &ldquo;closes in&rdquo; column yet. &ldquo;Opened&rdquo;
          is when we entered the position; a closed/resolved market simply moves to the Closed tab.
        </p>
      </div>
    </>
  )
}

function ClosedPositionsView() {
  const [filter, setFilter] = useState<CategoryFilter>('All')
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState<ClosedPositionsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Changing the category filter without resetting the page could land you
  // past the end of a much shorter filtered list.
  useEffect(() => { setOffset(0) }, [filter])

  useEffect(() => {
    let cancelled = false
    const category = filter === 'All' ? 'ALL' : filter
    setData(null)
    api
      .getClosedPositions(category, PAGE_SIZE, offset)
      .then((res) => { if (!cancelled) { setData(res); setError(null) } })
      .catch(() => { if (!cancelled) setError('Failed to load closed positions') })
    return () => { cancelled = true }
  }, [filter, offset])

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const totalCost = items.reduce((sum, p) => sum + p.cost_usd, 0)
  const totalPnl = items.reduce((sum, p) => sum + p.realized_pnl, 0)
  const totalPnlPct = totalCost ? (totalPnl / totalCost) * 100 : 0
  const wins = items.filter((p) => p.won).length

  return (
    <>
      {error && (
        <div className="rounded-xl bg-red-500/10 border border-red-500/30 p-4 flex items-center gap-3 mb-4">
          <AlertCircle className="h-5 w-5 text-red-400" />
          <p className="text-red-400">{error}</p>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <CategoryFilterBar value={filter} onChange={setFilter} />
        {data && <PaginationBar total={total} offset={offset} pageSize={PAGE_SIZE} onOffsetChange={setOffset} />}
      </div>

      <div className="rounded-xl bg-slate-900/50 border border-slate-800 overflow-hidden">
        <div className="overflow-x-auto">
          <div className="min-w-[980px]">
            <div className="grid grid-cols-12 gap-4 p-4 bg-slate-800/50 text-xs font-medium text-slate-400 uppercase tracking-wider border-b border-slate-800">
              <div className="col-span-2">Fund</div>
              <div className="col-span-3">Market</div>
              <div className="col-span-2">Bet on</div>
              <div className="col-span-1 text-right">Cost</div>
              <div className="col-span-1 text-center">Result</div>
              <div className="col-span-1">Resolved</div>
              <div className="col-span-2 text-right">P&amp;L</div>
            </div>

            {data === null ? (
              <TableSkeleton cols={[2, 3, 2, 1, 1, 1, 2]} />
            ) : items.length === 0 ? (
              <div className="p-10 text-center">
                <Activity className="h-10 w-10 text-slate-600 mx-auto mb-3" />
                <p className="text-slate-400">No closed positions yet</p>
              </div>
            ) : (
              <div className="divide-y divide-slate-800">
                {items.map((p, i) => (
                  <div
                    key={`${p.fund_id}-${p.token_id}-${i}`}
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
                        entry {(p.avg_entry_price * 100).toFixed(1)}&cent;
                      </p>
                    </div>

                    <div className="col-span-1 text-right text-slate-300 font-mono text-sm">
                      {formatCurrency(p.cost_usd)}
                    </div>

                    <div className="col-span-1 flex justify-center">
                      {p.won ? (
                        <span className="flex items-center gap-1 text-green-400 text-xs font-medium" title="This outcome happened">
                          <CheckCircle2 className="h-4 w-4" /> Won
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-red-400 text-xs font-medium" title="This outcome did not happen">
                          <XCircle className="h-4 w-4" /> Lost
                        </span>
                      )}
                    </div>

                    <div className="col-span-1">
                      <span
                        className="text-xs text-slate-400"
                        title={p.resolved_at ? apiDate(p.resolved_at).toLocaleString() : undefined}
                      >
                        {getTimeAgo(p.resolved_at)}
                      </span>
                    </div>

                    <div className="col-span-2 text-right">
                      <div className={cn(
                        'flex items-center justify-end gap-1 font-semibold text-sm',
                        p.realized_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                      )}>
                        {p.realized_pnl >= 0 ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
                        <span>
                          {p.realized_pnl >= 0 ? '+' : '−'}{formatCurrency(Math.abs(p.realized_pnl))}
                        </span>
                        {p.realized_pnl_pct !== null && (
                          <span className="text-xs text-slate-500 ml-1">
                            ({formatPercent(p.realized_pnl_pct)})
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {items.length > 0 && (
              <div className="grid grid-cols-12 gap-4 p-4 bg-slate-800/50 border-t border-slate-700 font-semibold">
                <div className="col-span-2 text-slate-300">This page</div>
                <div className="col-span-5 text-slate-500 text-xs self-center">
                  {items.length} position{items.length === 1 ? '' : 's'} &middot; {wins} won &middot; {items.length - wins} lost
                </div>
                <div className="col-span-1 text-right text-slate-300 font-mono text-sm">
                  {formatCurrency(totalCost)}
                </div>
                <div className="col-span-1" />
                <div className="col-span-1" />
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

      <p className="text-xs text-slate-500 mt-3 text-center">
        Totals above are for this page only, not the full {total.toLocaleString()} settled positions
        &mdash; realized P&amp;L for the whole history lives on each fund&apos;s page.
      </p>
    </>
  )
}

export default function PositionsPage() {
  const [view, setView] = useState<'open' | 'closed'>('open')

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <Layers className="h-7 w-7 text-aware-400" />
          Positions
        </h1>
        <p className="text-slate-400 mt-1">
          Every position every fund holds or has held, copy and active strategies together.
        </p>
      </div>

      <div className="flex gap-1 p-1 bg-slate-800/50 rounded-lg w-fit">
        {(['open', 'closed'] as const).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={cn(
              'px-4 py-2 text-sm font-medium rounded-md transition-all capitalize',
              view === v ? 'bg-aware-500 text-white' : 'text-slate-400 hover:text-white'
            )}
          >
            {v}
          </button>
        ))}
      </div>

      {view === 'open' ? <OpenPositionsView /> : <ClosedPositionsView />}
    </div>
  )
}
