'use client'

import { Suspense, useState, useEffect } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  Users,
  Activity,
  PieChart,
  BarChart2,
  Loader2,
  AlertCircle,
  ArrowUpRight,
  ArrowDownRight,
  ChevronDown,
  Zap,
} from 'lucide-react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { apiDate, cn, formatCurrency, formatNumber, formatPercent } from '@/lib/utils'
import { FundPnlChart } from '@/components/fund/FundPnlChart'
import { api, FundComparison } from '@/lib/api'

// Fund colors for chart
const fundColors: Record<string, string> = {
  'PSI-10': '#0ea5e9',
  'PSI-25': '#06b6d4',
  'PSI-CRYPTO': '#8b5cf6',
  'PSI-POLITICS': '#f59e0b',
  'PSI-SPORTS': '#22c55e',
  'ALPHA-ARB': '#ec4899',
  'ALPHA-INSIDER': '#f97316',
  'ALPHA-EDGE': '#14b8a6',
}

// Types
interface FundOverview {
  fund_id: string
  nav: number
  capital: number
  position_value: number
  unrealized_pnl: number
  realized_pnl: number
  total_return: number
  /** Every position attributed to the fund, open and settled. */
  total_positions: number
  last_updated: string
  /** False before the strategy has filled anything for this fund. */
  has_data: boolean
  /** True when the figures are split across funds that copied the same token,
   *  rather than attributed exactly. */
  apportioned: boolean
}

interface FundPosition {
  token_id: string
  market_slug: string
  title: string
  outcome: string
  shares: number
  cost_usd: number
  avg_entry_price: number
  /** null when the token has no recent print, so the position cannot be valued. */
  current_price: number | null
  current_value: number | null
  unrealized_pnl: number | null
  unrealized_pnl_pct: number | null
  priced_at: string | null
}

interface IndexConstituent {
  rank: number
  username: string
  proxy_address: string
  pseudonym: string
  weight: number
  total_score: number
  sharpe_ratio: number
  strategy_type: string
}

// Fund type configurations
/**
 * The funds are configured on the strategy service, not here. This page used
 * to keep its own hardcoded copy of the list, which had drifted: it carried
 * PSI-POLITICS, which is not enabled, and was missing PSI-ALPHA, which is. A
 * fund absent from the local list fell through `|| fundTypes[0]`, so opening
 * PSI-ALPHA showed PSI-10's name and description above PSI-ALPHA's numbers.
 * The list now comes from the API, so the two cannot drift again.
 */
interface FundTypeInfo {
  id: string
  name: string
  type: string
  description: string
}

// username is often empty; fall back to the pseudonym, then the address.
function constituentName(c: IndexConstituent): string {
  if (c.username) return c.username
  if (c.pseudonym) return c.pseudonym
  if (c.proxy_address) return `${c.proxy_address.slice(0, 6)}...${c.proxy_address.slice(-4)}`
  return `Trader #${c.rank}`
}

function FundPageContent() {
  const searchParams = useSearchParams()
  // PSI-10 is the landing fund because it is first in the display order the
  // API defines, not because it is the best performing one — that changes.
  const typeParam = searchParams.get('type') || 'PSI-10'

  const [selectedFund, setSelectedFund] = useState(typeParam)
  const [showFundSelector, setShowFundSelector] = useState(false)
  const [overview, setOverview] = useState<FundOverview | null>(null)
  const [positions, setPositions] = useState<FundPosition[]>([])
  const [constituents, setConstituents] = useState<IndexConstituent[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [comparisonTimeframe, setComparisonTimeframe] = useState('1M')
  const [comparison, setComparison] = useState<FundComparison | null>(null)
  const [fundTypes, setFundTypes] = useState<FundTypeInfo[] | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getFundsSummary()
      .then((s) => {
        if (cancelled) return
        setFundTypes(
          s.funds.map((f) => ({
            id: f.fund_id,
            name: f.fund_id,
            type: f.category,
            description: f.description,
          }))
        )
      })
      .catch(() => { if (!cancelled) setFundTypes([]) })
    return () => { cancelled = true }
  }, [])

  // Real ROI per fund over time, for the comparison chart below.
  useEffect(() => {
    const days = comparisonTimeframe === '1W' ? 7
      : comparisonTimeframe === '1M' ? 30
      : comparisonTimeframe === '3M' ? 90
      : 365
    let cancelled = false
    api
      .getFundComparison(days)
      .then((c) => { if (!cancelled) setComparison(c) })
      .catch(() => { if (!cancelled) setComparison(null) })
    return () => { cancelled = true }
  }, [comparisonTimeframe])

  // The span the chart actually covers, when it is shorter than the window
  // asked for. Null once the data fills the range and the buttons do bite.
  const comparisonSpan = (() => {
    const pts = comparison?.points ?? []
    if (pts.length < 2) return null
    const first = apiDate(pts[0].timestamp)
    const last = apiDate(pts[pts.length - 1].timestamp)
    const days = (last.getTime() - first.getTime()) / 86_400_000
    const requested = comparisonTimeframe === '1W' ? 7
      : comparisonTimeframe === '1M' ? 30
      : comparisonTimeframe === '3M' ? 90
      : 365
    if (days >= requested * 0.9) return null
    if (days < 1) {
      const hours = Math.max(1, Math.round(days * 24))
      return `${hours}h of history`
    }
    return `${Math.round(days)} days of history`
  })()

  // No fallback to the first fund: showing one fund's name over another's
  // numbers is worse than saying the id is not one we run.
  const currentFund = fundTypes?.find(f => f.id === selectedFund) ?? null
  const isMirrorFund = currentFund?.type === 'MIRROR'

  useEffect(() => {
    async function fetchFundData() {
      try {
        setError(null)

        const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

        // Real P&L for this fund. /api/fund/nav reports a NAV derived from
        // investor deposits and a positions table nothing writes, so it is
        // 10,000 and zeros for every fund; this reads what the strategies
        // actually did.
        const pnlResponse = await fetch(`${API_BASE}/api/fund/pnl?fund_id=${selectedFund}`)
        if (pnlResponse.ok) {
          const p = await pnlResponse.json()
          setOverview({
            fund_id: selectedFund,
            nav: p.cost_usd + p.total_pnl,
            capital: p.cost_usd,
            position_value: p.cost_usd + p.unrealized_pnl,
            unrealized_pnl: p.unrealized_pnl,
            realized_pnl: p.realized_pnl,
            total_return: p.roi_pct,
            total_positions: p.positions,
            last_updated: p.calculated_at || new Date().toISOString(),
            has_data: p.has_data,
            apportioned: p.apportioned,
          })
        } else {
          setOverview(null)
        }

        // Fetch positions
        const posResponse = await fetch(`${API_BASE}/api/fund/positions?fund_id=${selectedFund}`)
        if (posResponse.ok) {
          const posData = await posResponse.json()
          setPositions(Array.isArray(posData) ? posData : posData.positions || [])
        } else {
          setPositions([])
        }

        // Fetch index constituents for MIRROR funds
        if (isMirrorFund) {
          const indexResponse = await fetch(`${API_BASE}/api/fund/index?index_type=${selectedFund}`)
          if (indexResponse.ok) {
            const indexData = await indexResponse.json()
            const mappedConstituents = (indexData.constituents || []).map((c: any) => ({
              rank: c.rank,
              username: c.username,
              proxy_address: c.proxy_address,
              pseudonym: c.pseudonym,
              weight: c.weight / 100,
              total_score: c.smart_money_score,
              sharpe_ratio: c.sharpe_ratio,
              strategy_type: c.strategy_type,
            }))
            setConstituents(mappedConstituents)
          } else {
            setConstituents([])
          }
        } else {
          setConstituents([])
        }

      } catch (err) {
        console.error('Fund data fetch error:', err)
        setError('Failed to load fund data')
      } finally {
        setIsLoading(false)
      }
    }

    // First paint shows the skeleton; the 30s refresh does not. Flipping back
    // to the loading state on every poll blanked the whole page twice a minute
    // and read as an automatic reload.
    setIsLoading(true)
    fetchFundData()
    const interval = setInterval(fetchFundData, 30000)
    return () => clearInterval(interval)
  }, [selectedFund, isMirrorFund])

  const totalReturn = overview ? overview.nav - overview.capital : 0
  const returnPct = overview && overview.capital > 0 ? (totalReturn / overview.capital) * 100 : 0
  const isPositive = totalReturn >= 0

  if (fundTypes === null) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="h-8 w-8 text-aware-400 animate-spin" />
        <span className="ml-3 text-slate-400">Loading funds...</span>
      </div>
    )
  }

  if (!currentFund) {
    return (
      <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-6">
        <h1 className="text-xl font-bold text-white">Unknown fund</h1>
        <p className="text-slate-400 mt-1">
          <span className="font-mono">{selectedFund}</span> is not one of the
          funds currently running.
        </p>
        {fundTypes.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-4">
            {fundTypes.map((f) => (
              <button
                key={f.id}
                onClick={() => setSelectedFund(f.id)}
                className="px-3 py-1.5 text-sm rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700"
              >
                {f.name}
              </button>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            {isMirrorFund ? (
              <Users className="h-7 w-7 text-blue-400" />
            ) : (
              <Zap className="h-7 w-7 text-purple-400" />
            )}
            {currentFund.name} Fund
          </h1>
          <p className="text-slate-400 mt-1">
            {currentFund.description}
          </p>
        </div>

        {/* Fund Selector */}
        <div className="relative">
          <button
            onClick={() => setShowFundSelector(!showFundSelector)}
            className="flex items-center gap-2 px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg hover:bg-slate-700 transition-colors"
          >
            <span className={cn(
              'text-xs px-2 py-0.5 rounded-full',
              isMirrorFund ? 'bg-blue-500/20 text-blue-400' : 'bg-purple-500/20 text-purple-400'
            )}>
              {currentFund.type}
            </span>
            <span className="text-white font-medium">{currentFund.name}</span>
            <ChevronDown className={cn(
              'w-4 h-4 text-slate-400 transition-transform',
              showFundSelector && 'rotate-180'
            )} />
          </button>

          {showFundSelector && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setShowFundSelector(false)}
              />
              <div className="absolute right-0 mt-2 w-64 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-50 overflow-hidden">
                {fundTypes.map((fund) => (
                  <button
                    key={fund.id}
                    onClick={() => {
                      setSelectedFund(fund.id)
                      setShowFundSelector(false)
                    }}
                    className={cn(
                      'w-full px-4 py-3 text-left hover:bg-slate-700/50 transition-colors flex items-center justify-between',
                      selectedFund === fund.id && 'bg-aware-500/10'
                    )}
                  >
                    <div>
                      <p className="text-white font-medium">{fund.name}</p>
                      <p className="text-xs text-slate-500">{fund.description}</p>
                    </div>
                    <span className={cn(
                      'text-xs px-2 py-0.5 rounded-full',
                      fund.type === 'MIRROR' ? 'bg-blue-500/20 text-blue-400' : 'bg-purple-500/20 text-purple-400'
                    )}>
                      {fund.type}
                    </span>
                  </button>
                ))}

                <div className="border-t border-slate-700 p-2">
                  <Link
                    href="/funds"
                    className="block w-full px-3 py-2 text-sm text-aware-400 hover:text-aware-300 text-center"
                  >
                    View All Funds →
                  </Link>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="rounded-xl bg-red-500/10 border border-red-500/30 p-4 flex items-center gap-3">
          <AlertCircle className="h-5 w-5 text-red-400" />
          <p className="text-red-400">{error}</p>
        </div>
      )}

      {/* Loading State */}
      {isLoading && (
        <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-12 flex items-center justify-center">
          <Loader2 className="h-8 w-8 text-aware-400 animate-spin" />
          <span className="ml-3 text-slate-400">Loading fund data...</span>
        </div>
      )}

      {!isLoading && overview && (
        <>
          {/* Headline figures */}
          <div className={cn(
            'rounded-xl border p-6',
            isMirrorFund
              ? 'bg-gradient-to-br from-blue-500/10 to-cyan-500/10 border-blue-500/30'
              : 'bg-gradient-to-br from-purple-500/10 to-violet-500/10 border-purple-500/30'
          )}>
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                <div>
                  <p className="text-slate-400 text-sm">Current value</p>
                  <div className="flex items-baseline gap-3 mt-1">
                    <span className="text-4xl font-bold text-white">
                      {overview.has_data ? formatCurrency(overview.nav) : '\u2014'}
                    </span>
                    {overview.has_data && (
                      <span className={cn(
                        'flex items-center text-lg font-semibold',
                        isPositive ? 'text-green-400' : 'text-red-400'
                      )}>
                        {isPositive ? <ArrowUpRight className="h-5 w-5" /> : <ArrowDownRight className="h-5 w-5" />}
                        {returnPct.toFixed(2)}%
                      </span>
                    )}
                  </div>
                  {overview.has_data ? (
                    <>
                      <p className="text-slate-500 text-sm mt-1">
                        Invested: {formatCurrency(overview.capital)}
                        {' \u00b7 '}
                        {overview.total_positions} position{overview.total_positions === 1 ? '' : 's'}
                      </p>
                      {overview.apportioned && (
                        <p
                          className="text-slate-600 text-xs mt-1"
                          title="Several funds copy the same market, so each result is split by how many shares each fund asked for."
                        >
                          Figures apportioned across funds sharing a position
                        </p>
                      )}
                    </>
                  ) : (
                    <p className="text-slate-500 text-sm mt-1">
                      This fund has not traded yet. Numbers appear once it fills
                      its first order.
                    </p>
                  )}
                </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="bg-slate-800/50 rounded-lg p-4 text-center">
                  <p className={cn(
                    'text-2xl font-bold',
                    overview.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                  )}>
                    {formatCurrency(overview.unrealized_pnl)}
                  </p>
                  <p className="text-xs text-slate-500">Unrealized P&L</p>
                </div>
                <div className="bg-slate-800/50 rounded-lg p-4 text-center">
                  <p className={cn(
                    'text-2xl font-bold',
                    overview.realized_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                  )}>
                    {formatCurrency(overview.realized_pnl)}
                  </p>
                  <p className="text-xs text-slate-500">Realized P&L</p>
                </div>
              </div>
            </div>
          </div>

          {/* P&L over time */}
          <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-6">
            <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
              <Activity className="w-5 h-5 text-aware-400" />
              P&L History
            </h3>
            <FundPnlChart fundId={selectedFund} height={300} />
          </div>

          {/* Fund Performance Comparison Chart */}
          <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-6">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-semibold text-white">Fund Performance Comparison</h3>
              <div className="flex gap-1 p-1 bg-slate-800/50 rounded-lg">
                {['1W', '1M', '3M', 'ALL'].map((tf) => (
                  <button
                    key={tf}
                    onClick={() => setComparisonTimeframe(tf)}
                    className={cn(
                      'px-3 py-1.5 text-xs font-medium rounded-md transition-all',
                      comparisonTimeframe === tf
                        ? 'bg-aware-500 text-white'
                        : 'text-slate-400 hover:text-white'
                    )}
                  >
                    {tf}
                  </button>
                ))}
              </div>
            </div>
            {!comparison || comparison.points.length < 2 ? (
              <div className="h-72 flex flex-col items-center justify-center text-center">
                <p className="text-sm text-slate-400">Not enough history yet</p>
                <p className="text-xs text-slate-500 mt-1 max-w-sm">
                  A point is recorded each time the analytics pipeline runs. The
                  comparison appears once there are at least two.
                </p>
              </div>
            ) : (
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={comparison.points}>
                    <defs>
                      {comparison.funds.map((fundId) => (
                        <linearGradient key={fundId} id={`color-${fundId}`} x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={fundColors[fundId] || '#64748b'} stopOpacity={0.2} />
                          <stop offset="95%" stopColor={fundColors[fundId] || '#64748b'} stopOpacity={0} />
                        </linearGradient>
                      ))}
                    </defs>
                    <XAxis
                      dataKey="timestamp"
                      tickFormatter={(v) => apiDate(v as string).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: '#64748b', fontSize: 12 }}
                      minTickGap={40}
                    />
                    <YAxis
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: '#64748b', fontSize: 12 }}
                      tickFormatter={(v) => `${v}%`}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#1e293b',
                        border: '1px solid #334155',
                        borderRadius: '8px'
                      }}
                      labelFormatter={(v) => apiDate(v as string).toLocaleString()}
                      formatter={(value, name) => [`${Number(value).toFixed(1)}%`, name]}
                    />
                    <Legend />
                    {comparison.funds.map((fundId) => (
                      <Area
                        key={fundId}
                        type="monotone"
                        dataKey={fundId}
                        stroke={fundColors[fundId] || '#64748b'}
                        strokeWidth={selectedFund === fundId ? 3 : 1.5}
                        fill={`url(#color-${fundId})`}
                        opacity={selectedFund === fundId ? 1 : 0.5}
                        dot={false}
                        connectNulls
                      />
                    ))}
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
            <p className="text-xs text-slate-500 mt-3 text-center">
              Return on deployed capital. Funds that have not traded are omitted.
              {comparisonSpan && (
                <>
                  {' '}
                  Showing {comparisonSpan}
                  {' \u2014 '}
                  shorter than the selected range, so the window buttons will
                  look identical until more history accumulates.
                </>
              )}
            </p>
          </div>

          {/* Stats Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-4">
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 rounded-lg bg-blue-500/10">
                  <DollarSign className="h-5 w-5 text-blue-400" />
                </div>
                <span className="text-slate-400 text-sm">Position Value</span>
              </div>
              <p className="text-2xl font-bold text-white">
                {formatCurrency(overview.position_value)}
              </p>
            </div>

            <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-4">
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 rounded-lg bg-green-500/10">
                  <Activity className="h-5 w-5 text-green-400" />
                </div>
                <span
                  className="text-slate-400 text-sm"
                  title="Every position the fund has taken, including markets that have already resolved. The card below lists only the ones still open."
                >
                  Positions Taken
                </span>
              </div>
              <p className="text-2xl font-bold text-white">
                {overview.total_positions}
              </p>
              <p className="text-xs text-slate-500 mt-1">
                {positions.length} still open
              </p>
            </div>

            {isMirrorFund && (
              <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-4">
                <div className="flex items-center gap-3 mb-2">
                  <div className="p-2 rounded-lg bg-purple-500/10">
                    <Users className="h-5 w-5 text-purple-400" />
                  </div>
                  <span className="text-slate-400 text-sm">Tracked Traders</span>
                </div>
                <p className="text-2xl font-bold text-white">
                  {constituents.length}
                </p>
              </div>
            )}

            <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-4">
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 rounded-lg bg-yellow-500/10">
                  <TrendingUp className="h-5 w-5 text-yellow-400" />
                </div>
                <span className="text-slate-400 text-sm">Total Return</span>
              </div>
              <p className={cn(
                'text-2xl font-bold',
                isPositive ? 'text-green-400' : 'text-red-400'
              )}>
                {isPositive ? '+' : ''}{returnPct.toFixed(2)}%
              </p>
            </div>
          </div>

          {/* Two Column Layout */}
          <div className="grid lg:grid-cols-2 gap-6">
            {/* Positions Table */}
            <div className="rounded-xl bg-slate-900/50 border border-slate-800 overflow-hidden">
              <div className="p-4 border-b border-slate-800">
                <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                  <BarChart2 className="h-5 w-5 text-aware-400" />
                  Open Positions
                </h2>
              </div>

              {positions.length === 0 ? (
                <div className="p-8 text-center">
                  <Activity className="h-12 w-12 text-slate-600 mx-auto mb-4" />
                  <p className="text-slate-400">No open positions</p>
                  <p className="text-sm text-slate-500 mt-1">
                    {overview.total_positions > 0
                      ? 'Every market this fund traded has already resolved.'
                      : isMirrorFund
                        ? 'Fund will open positions when tracked traders trade'
                        : 'Waiting for trading signals'}
                  </p>
                </div>
              ) : (
                <div className="divide-y divide-slate-800 max-h-96 overflow-y-auto">
                  {positions.map((pos) => (
                    <div key={pos.token_id} className="p-4 hover:bg-slate-800/30">
                      <div className="flex justify-between items-start gap-3">
                        <div className="min-w-0">
                          <p className="text-white font-medium line-clamp-2">
                            {pos.title || pos.market_slug}
                          </p>
                          <p className="text-sm text-slate-400">
                            {formatNumber(pos.shares, 2)} shares @ {pos.outcome} ·
                            entry {(pos.avg_entry_price * 100).toFixed(0)}¢
                          </p>
                        </div>
                        <div className="text-right shrink-0">
                          {pos.unrealized_pnl === null ? (
                            <>
                              <p
                                className="font-semibold text-slate-500"
                                title="No trade on this token recently, so there is no price to value it at"
                              >
                                —
                              </p>
                              <p className="text-sm text-slate-500">
                                {formatCurrency(pos.cost_usd)} cost
                              </p>
                            </>
                          ) : (
                            <>
                              <p className={cn(
                                'font-semibold',
                                pos.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                              )}>
                                {pos.unrealized_pnl >= 0 ? '+' : '\u2212'}
                                {formatCurrency(Math.abs(pos.unrealized_pnl))}
                              </p>
                              <p className="text-sm text-slate-500">
                                {formatCurrency(pos.current_value ?? 0)} value
                              </p>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Index Constituents (for MIRROR funds) or Strategy Info (for ACTIVE funds) */}
            {isMirrorFund ? (
              <div className="rounded-xl bg-slate-900/50 border border-slate-800 overflow-hidden">
                <div className="p-4 border-b border-slate-800">
                  <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                    <Users className="h-5 w-5 text-aware-400" />
                    {currentFund.name} Constituents
                  </h2>
                </div>

                {constituents.length === 0 ? (
                  <div className="p-8 text-center">
                    <Users className="h-12 w-12 text-slate-600 mx-auto mb-4" />
                    <p className="text-slate-400">No index data</p>
                    <p className="text-sm text-slate-500 mt-1">
                      Run the analytics pipeline to build the index
                    </p>
                  </div>
                ) : (
                  <div className="divide-y divide-slate-800 max-h-96 overflow-y-auto">
                    {constituents.map((c, i) => (
                      <div key={c.rank} className="p-4 hover:bg-slate-800/30 flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <span className="text-slate-500 font-medium w-6">{i + 1}</span>
                          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-aware-400 to-aware-600 flex items-center justify-center text-white text-sm font-bold">
                            {constituentName(c).charAt(0).toUpperCase()}
                          </div>
                          <div>
                            <p className="text-white font-medium">{constituentName(c)}</p>
                            <p className="text-xs text-slate-500">{c.strategy_type}</p>
                          </div>
                        </div>
                        <div className="text-right">
                          <p className="text-white font-medium">
                            {(c.weight * 100).toFixed(1)}%
                          </p>
                          <p className="text-xs text-slate-500">
                            Score: {c.total_score.toFixed(0)}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="rounded-xl bg-slate-900/50 border border-slate-800 overflow-hidden">
                <div className="p-4 border-b border-slate-800">
                  <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                    <Zap className="h-5 w-5 text-purple-400" />
                    Strategy Details
                  </h2>
                </div>
                <div className="p-6">
                  <div className="space-y-4">
                    {selectedFund === 'ALPHA-ARB' && (
                      <>
                        <div>
                          <p className="text-slate-400 text-sm">Strategy Type</p>
                          <p className="text-white font-medium">Complete-Set Arbitrage</p>
                        </div>
                        <div>
                          <p className="text-slate-400 text-sm">Description</p>
                          <p className="text-white">Exploits price discrepancies by buying complete sets when outcomes sum to less than $1</p>
                        </div>
                      </>
                    )}
                    {selectedFund === 'ALPHA-INSIDER' && (
                      <>
                        <div>
                          <p className="text-slate-400 text-sm">Strategy Type</p>
                          <p className="text-white font-medium">Insider Activity Detection</p>
                        </div>
                        <div>
                          <p className="text-slate-400 text-sm">Description</p>
                          <p className="text-white">Follows unusual trading patterns that suggest informed trading activity</p>
                        </div>
                      </>
                    )}
                    {selectedFund === 'ALPHA-EDGE' && (
                      <>
                        <div>
                          <p className="text-slate-400 text-sm">Strategy Type</p>
                          <p className="text-white font-medium">ML Edge Predictions</p>
                        </div>
                        <div>
                          <p className="text-slate-400 text-sm">Description</p>
                          <p className="text-white">Uses machine learning to identify high-probability trading opportunities</p>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Fund Info */}
          <div className="rounded-xl bg-slate-800/30 border border-slate-800 p-6">
            <h3 className="text-lg font-semibold text-white mb-4">About This Fund</h3>
            <div className="grid md:grid-cols-3 gap-6 text-sm">
              <div>
                <p className="text-slate-400">Strategy</p>
                <p className="text-white mt-1">{currentFund.description}</p>
              </div>
              <div>
                <p className="text-slate-400">Execution</p>
                <p className="text-white mt-1">
                  {isMirrorFund
                    ? '5-second delay after detecting trader trades, limit orders with market fallback'
                    : 'Algorithmic execution based on strategy signals'}
                </p>
              </div>
              <div>
                <p className="text-slate-400">Risk Controls</p>
                <p className="text-white mt-1">
                  Max 10% per position, 10% max drawdown circuit breaker
                </p>
              </div>
            </div>
          </div>

          {/* Quick Actions */}
          <div className="flex justify-center gap-4">
            <Link
              href="/funds"
              className="px-6 py-3 bg-slate-700 hover:bg-slate-600 text-white font-medium rounded-lg transition-colors"
            >
              Compare Funds
            </Link>
          </div>
        </>
      )}
    </div>
  )
}

export default function FundPage() {
  return (
    <Suspense fallback={
      <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-12 flex items-center justify-center">
        <Loader2 className="h-8 w-8 text-aware-400 animate-spin" />
        <span className="ml-3 text-slate-400">Loading fund details...</span>
      </div>
    }>
      <FundPageContent />
    </Suspense>
  )
}
