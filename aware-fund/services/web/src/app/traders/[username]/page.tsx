'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import {
  ArrowLeft,
  TrendingUp,
  TrendingDown,
  Target,
  Clock,
  BarChart3,
  Activity,
  Star,
  Shield,
  Loader2,
} from 'lucide-react'
import { Skeleton, SkeletonChart, SkeletonRows } from '@/components/ui/Loading'
import { apiDate, cn, formatCurrency, formatNumber, getTimeAgo } from '@/lib/utils'
import {
  AreaChart,
  Area,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts'
import {
  api,
  TraderProfile,
  TraderActivity,
  TraderCategory,
  traderName,
  traderInitial,
} from '@/lib/api'

/**
 * Categorical hues for the category donut. Every slice touches every other one
 * in a donut, so these were validated all-pairs against the dark surface rather
 * than only as adjacent neighbours — which is why there is one blue and not two.
 * Four is the ceiling that stays separable; anything beyond folds into "Other",
 * drawn in neutral slate because it is a remainder, not a category.
 */
const CATEGORY_COLORS = ['#0284c7', '#d97706', '#8b5cf6', '#db2777']
const OTHER_COLOR = '#475569'
const MAX_SLICES = 4

const AXIS = '#64748b'
const GRID = '#1e293b'

const tierStyles: Record<string, string> = {
  Diamond: 'bg-gradient-to-r from-cyan-400 to-blue-400 text-slate-900',
  DIAMOND: 'bg-gradient-to-r from-cyan-400 to-blue-400 text-slate-900',
  Gold: 'bg-gradient-to-r from-yellow-400 to-amber-400 text-slate-900',
  GOLD: 'bg-gradient-to-r from-yellow-400 to-amber-400 text-slate-900',
  Silver: 'bg-gradient-to-r from-slate-300 to-slate-400 text-slate-900',
  SILVER: 'bg-gradient-to-r from-slate-300 to-slate-400 text-slate-900',
  Bronze: 'bg-gradient-to-r from-orange-400 to-amber-600 text-white',
  BRONZE: 'bg-gradient-to-r from-orange-400 to-amber-600 text-white',
}

const formatTier = (tier: string) => tier.charAt(0).toUpperCase() + tier.slice(1).toLowerCase()

const prettyCategory = (c: string) =>
  c === 'UNCLASSIFIED' ? 'Unclassified' : c.charAt(0) + c.slice(1).toLowerCase()

const shortDate = (iso: string) =>
  apiDate(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

const cents = (p: number) => `${(p * 100).toFixed(0)}¢`

/** Top slices kept whole, the tail summed into one neutral remainder. */
function foldCategories(categories: TraderCategory[]) {
  const ranked = [...categories].sort((a, b) => b.volume - a.volume)
  const head = ranked.slice(0, MAX_SLICES)
  const tail = ranked.slice(MAX_SLICES)
  const slices = head.map((c, i) => ({
    key: c.category,
    label: prettyCategory(c.category),
    share_pct: c.share_pct,
    trade_count: c.trade_count,
    win_rate: c.win_rate,
    color: CATEGORY_COLORS[i],
  }))
  if (tail.length) {
    slices.push({
      key: '__other__',
      label: `Other (${tail.length})`,
      share_pct: Math.round(tail.reduce((s, c) => s + c.share_pct, 0) * 10) / 10,
      trade_count: tail.reduce((s, c) => s + c.trade_count, 0),
      win_rate: null,
      color: OTHER_COLOR,
    })
  }
  return slices
}

/**
 * Goes back where the reader came from.
 *
 * This said "Back to Leaderboard" and linked there unconditionally, which was
 * wrong the moment a trader could be opened from a fund's constituent list.
 * History knows the answer; the leaderboard is the fallback for anyone who
 * arrived at the URL directly.
 */
function BackLink() {
  const router = useRouter()
  const [canGoBack, setCanGoBack] = useState(false)

  useEffect(() => {
    setCanGoBack(typeof window !== 'undefined' && window.history.length > 1)
  }, [])

  const className =
    'inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors'

  if (canGoBack) {
    return (
      <button type="button" onClick={() => router.back()} className={className}>
        <ArrowLeft className="h-4 w-4" />
        Back
      </button>
    )
  }
  return (
    <Link href="/leaderboard" className={className}>
      <ArrowLeft className="h-4 w-4" />
      Back to Leaderboard
    </Link>
  )
}

export default function TraderProfilePage() {
  const params = useParams()
  const [activeTab, setActiveTab] = useState<'overview' | 'positions' | 'history'>('overview')
  const [trader, setTrader] = useState<TraderProfile | null>(null)
  const [activity, setActivity] = useState<TraderActivity | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function fetchTrader() {
      const username = params.username as string
      if (!username) return

      try {
        setIsLoading(true)
        setError(null)
        const data = await api.getTrader(username)
        setTrader(data)

        // Second call, deliberately not awaited together with the first: the
        // header can render as soon as the profile lands, and the activity
        // query is keyed on the address the profile returns.
        if (data.proxy_address) {
          api
            .getTraderActivity(data.proxy_address)
            .then(setActivity)
            .catch((err) => console.error('Trader activity fetch error:', err))
        }
      } catch (err) {
        setError('Failed to load trader profile. Make sure the API server is running.')
        console.error('Trader fetch error:', err)
      } finally {
        setIsLoading(false)
      }
    }
    fetchTrader()
  }, [params.username])

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-6">
          <div className="flex flex-col md:flex-row md:items-start justify-between gap-6">
            <div className="flex items-start gap-4">
              <Skeleton className="w-20 h-20 rounded-2xl" />
              <div className="space-y-2">
                <Skeleton className="h-7 w-44" />
                <Skeleton className="h-4 w-56" />
                <Skeleton className="h-4 w-40" />
              </div>
            </div>
            <div className="flex gap-6">
              {[0, 1, 2].map((i) => (
                <div key={i} className="space-y-2">
                  <Skeleton className="h-8 w-20" />
                  <Skeleton className="h-3 w-24" />
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="rounded-lg bg-slate-800/50 p-4 space-y-2">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-6 w-12" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (error || !trader) {
    return (
      <div className="space-y-6">
        <BackLink />
        <div className="rounded-xl bg-red-500/10 border border-red-500/30 p-6">
          <p className="text-red-400 font-medium">{error || 'Trader not found'}</p>
        </div>
      </div>
    )
  }

  const avgTradeSize = trader.total_trades > 0 ? trader.total_volume / trader.total_trades : 0
  const pending = activity === null

  return (
    <div className="space-y-6">
      <BackLink />

      {/* Profile Header */}
      <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-6">
        <div className="flex flex-col md:flex-row md:items-start justify-between gap-6">
          <div className="flex items-start gap-4">
            <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-aware-400 to-aware-600 flex items-center justify-center text-3xl font-bold text-white">
              {traderInitial(trader)}
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-2xl font-bold text-white">{traderName(trader)}</h1>
                <span
                  className={cn(
                    'px-3 py-1 text-sm font-semibold rounded-full',
                    tierStyles[trader.tier] || tierStyles['BRONZE']
                  )}
                >
                  {formatTier(trader.tier)}
                </span>
              </div>
              <p className="text-slate-500 text-sm mt-1 font-mono">
                {trader.proxy_address?.slice(0, 10)}...{trader.proxy_address?.slice(-8)}
              </p>
              <div className="flex items-center gap-4 mt-3">
                <div className="flex items-center gap-1 text-sm text-slate-400">
                  <Target className="h-4 w-4" />
                  {trader.strategy_type || 'Multi-category'}
                </div>
                <div className="flex items-center gap-1 text-sm text-slate-400">
                  <Clock className="h-4 w-4" />
                  {trader.days_active || 0} days active
                </div>
              </div>
            </div>
          </div>

          <div className="flex gap-6">
            <div className="text-center">
              <p className="text-3xl font-bold text-white">
                {(trader.smart_money_score || 0).toFixed(1)}
              </p>
              <p className="text-sm text-slate-500">Smart Money Score</p>
            </div>
            <div className="text-center">
              <p
                className={cn(
                  'text-3xl font-bold',
                  (trader.total_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'
                )}
              >
                {formatCurrency(trader.total_pnl || 0)}
              </p>
              <p className="text-sm text-slate-500">Total P&L</p>
            </div>
            <div className="text-center">
              <p className="text-3xl font-bold text-white">{trader.unique_markets || 0}</p>
              <p className="text-sm text-slate-500">Markets</p>
            </div>
          </div>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
        <StatBox label="Profitability" value={`${((trader.profitability_score || 0) * 100).toFixed(0)}%`} icon={Target} color="text-green-400" />
        <StatBox label="Risk-Adjusted" value={`${((trader.risk_adjusted_score || 0) * 100).toFixed(0)}%`} icon={BarChart3} color="text-aware-400" />
        <StatBox label="Total Trades" value={formatNumber(trader.total_trades || 0, 0)} icon={Activity} color="text-purple-400" />
        <StatBox label="Avg Trade" value={formatCurrency(avgTradeSize)} icon={TrendingUp} color="text-cyan-400" />
        <StatBox label="Consistency" value={`${((trader.consistency_score || 0) * 100).toFixed(0)}%`} icon={Shield} color="text-emerald-400" />
        <StatBox label="Track Record" value={`${((trader.track_record_score || 0) * 100).toFixed(0)}%`} icon={Star} color="text-yellow-400" />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-slate-800/50 rounded-lg w-fit">
        {(['overview', 'positions', 'history'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'px-4 py-2 text-sm font-medium rounded-md transition-all capitalize',
              activeTab === tab ? 'bg-aware-500 text-white' : 'text-slate-400 hover:text-white'
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <PnlCurveCard activity={activity} pending={pending} />
          <CategoryCard activity={activity} pending={pending} />
        </div>
      )}

      {activeTab === 'positions' && (
        <div className="space-y-6">
          <PositionsCard activity={activity} pending={pending} />
          <SettledCard activity={activity} pending={pending} />
        </div>
      )}

      {activeTab === 'history' && <HistoryCard activity={activity} pending={pending} />}
    </div>
  )
}

function Panel({
  title,
  caption,
  children,
}: {
  title: string
  caption?: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-xl bg-slate-900/50 border border-slate-800 overflow-hidden">
      <div className="p-5 border-b border-slate-800">
        <h3 className="font-semibold text-white">{title}</h3>
        {caption && <p className="text-xs text-slate-500 mt-0.5">{caption}</p>}
      </div>
      {children}
    </div>
  )
}

function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="py-12 px-5 text-center">
      <p className="text-sm text-slate-400">{title}</p>
      {hint && <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto">{hint}</p>}
    </div>
  )
}

function PnlCurveCard({
  activity,
  pending,
}: {
  activity: TraderActivity | null
  pending: boolean
}) {
  const points = activity?.pnl_curve ?? []
  // The curve can end below zero, so it is coloured by where it lands rather
  // than assumed green.
  const final = points.length ? points[points.length - 1].cumulative_pnl : 0
  const hue = final >= 0 ? '#22c55e' : '#ef4444'

  return (
    <Panel
      title="Cumulative realized P&L"
      caption="Settled markets only. Open positions are estimates and live in the Positions tab."
    >
      {pending ? (
        <div className="p-5">
          <SkeletonChart height={256} />
        </div>
      ) : points.length < 2 ? (
        <Empty
          title="Not enough settled history yet"
          hint="A point is added each day a market this trader held resolves. The curve appears once there are at least two."
        />
      ) : (
        <div className="p-5">
          <div className="h-64 -ml-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="traderPnlFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={hue} stopOpacity={0.22} />
                    <stop offset="100%" stopColor={hue} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="date"
                  tickFormatter={shortDate}
                  stroke={AXIS}
                  tick={{ fill: AXIS, fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  minTickGap={32}
                />
                <YAxis
                  stroke={AXIS}
                  tick={{ fill: AXIS, fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  width={56}
                  tickFormatter={(v) => formatCurrency(Number(v))}
                />
                {/* Break-even: above it the trader is up on settled markets. */}
                <CartesianGrid horizontalPoints={[0]} stroke="#334155" vertical={false} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#0f172a',
                    border: '1px solid #1e293b',
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  labelFormatter={(v) => apiDate(v as string).toLocaleDateString()}
                  formatter={(value, name) => [
                    formatCurrency(Number(value)),
                    name === 'cumulative_pnl' ? 'Cumulative' : 'That day',
                  ]}
                />
                <Area
                  type="monotone"
                  dataKey="cumulative_pnl"
                  stroke={hue}
                  strokeWidth={2}
                  fill="url(#traderPnlFill)"
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, stroke: '#0f172a' }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 pt-4 border-t border-slate-800 flex items-baseline gap-2">
            <span className="text-xs text-slate-500">Settled to date</span>
            <span
              className={cn(
                'text-lg font-semibold tabular-nums',
                final >= 0 ? 'text-green-400' : 'text-red-400'
              )}
            >
              {final >= 0 ? '+' : '−'}
              {formatCurrency(Math.abs(final))}
            </span>
          </div>
        </div>
      )}
    </Panel>
  )
}

function CategoryCard({
  activity,
  pending,
}: {
  activity: TraderActivity | null
  pending: boolean
}) {
  const slices = foldCategories(activity?.categories ?? [])

  return (
    <Panel title="Category breakdown" caption="Share of traded volume, by market category.">
      {pending ? (
        <div className="p-5 flex items-center gap-8">
          <Skeleton className="w-40 h-40 rounded-full shrink-0" />
          <div className="flex-1 space-y-3">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-4 w-full" />
            ))}
          </div>
        </div>
      ) : slices.length === 0 ? (
        <Empty title="No trades recorded for this wallet yet" />
      ) : (
        <div className="p-5 flex items-center gap-8">
          <div className="w-40 h-40 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={slices}
                  innerRadius={45}
                  outerRadius={70}
                  paddingAngle={4}
                  dataKey="share_pct"
                  nameKey="label"
                  stroke="none"
                >
                  {slices.map((s) => (
                    <Cell key={s.key} fill={s.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#0f172a',
                    border: '1px solid #1e293b',
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  formatter={(value, name) => [`${Number(value).toFixed(1)}%`, name]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          {/* Direct labels carry identity, so the slices never rest on colour
              alone — which is also what makes the tight hue pair legible. */}
          <div className="flex-1 space-y-3 min-w-0">
            {slices.map((s) => (
              <div key={s.key} className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className="w-2.5 h-2.5 rounded-sm shrink-0"
                    style={{ backgroundColor: s.color }}
                  />
                  <span className="text-sm text-slate-300 truncate">{s.label}</span>
                </div>
                <div className="text-right shrink-0">
                  <span className="text-sm font-medium text-white tabular-nums">
                    {s.share_pct.toFixed(1)}%
                  </span>
                  {s.win_rate !== null && (
                    <span className="text-xs text-slate-500 ml-2 tabular-nums">
                      {s.win_rate.toFixed(0)}% win
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  )
}

function PositionsCard({
  activity,
  pending,
}: {
  activity: TraderActivity | null
  pending: boolean
}) {
  const positions = activity?.open_positions ?? []
  const hours = activity?.mark_max_age_hours ?? 6

  return (
    <Panel
      title="Open positions"
      caption={`Net shares held in markets that have not resolved, marked to the last trade on each token. Positions with no trade in ${hours}h are left unpriced.`}
    >
      {pending ? (
        <SkeletonRows rows={3} />
      ) : positions.length === 0 ? (
        <Empty
          title="No open positions"
          hint="Every market this wallet traded has already resolved, or its buys and sells net out."
        />
      ) : (
        <div className="divide-y divide-slate-800">
          {positions.map((pos) => (
            <div
              key={`${pos.condition_id}-${pos.outcome}`}
              className="p-4 grid grid-cols-2 md:grid-cols-6 gap-4 items-center"
            >
              <div className="col-span-2">
                <p className="text-sm text-white font-medium line-clamp-2">{pos.title}</p>
                <span className="text-xs text-aware-400">{pos.outcome}</span>
              </div>
              <div className="text-right">
                <p className="text-sm text-white tabular-nums">{formatNumber(pos.shares, 0)}</p>
                <p className="text-xs text-slate-500">Shares</p>
              </div>
              <div className="text-right">
                <p className="text-sm text-white tabular-nums">{cents(pos.avg_entry_price)}</p>
                <p className="text-xs text-slate-500">Entry</p>
              </div>
              <div className="text-right">
                <p className="text-sm text-white tabular-nums">
                  {pos.current_price === null ? (
                    <span className="text-slate-500" title={`No trade on this token in the last ${hours}h`}>
                      —
                    </span>
                  ) : (
                    cents(pos.current_price)
                  )}
                </p>
                <p className="text-xs text-slate-500">
                  {pos.priced_at ? getTimeAgo(pos.priced_at) : 'No recent price'}
                </p>
              </div>
              <div className="text-right">
                {pos.unrealized_pnl === null ? (
                  <p className="text-sm text-slate-500">—</p>
                ) : (
                  <p
                    className={cn(
                      'text-sm font-medium tabular-nums',
                      pos.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                    )}
                  >
                    {pos.unrealized_pnl >= 0 ? '+' : '−'}
                    {formatCurrency(Math.abs(pos.unrealized_pnl))}
                  </p>
                )}
                <p className="text-xs text-slate-500">Unrealized</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

function SettledCard({
  activity,
  pending,
}: {
  activity: TraderActivity | null
  pending: boolean
}) {
  const settled = activity?.settled_positions ?? []
  const won = settled.filter((p) => p.won).length
  const net = settled.reduce((sum, p) => sum + p.realized_pnl, 0)

  return (
    <Panel
      title="Settled positions"
      caption={
        settled.length > 0
          ? `${won} of ${settled.length} resolved in their favour · ${
              net >= 0 ? '+' : '\u2212'
            }${formatCurrency(Math.abs(net))} net`
          : 'Markets this wallet held that have since resolved.'
      }
    >
      {pending ? (
        <SkeletonRows rows={4} />
      ) : settled.length === 0 ? (
        <Empty
          title="Nothing has settled yet"
          hint="Positions appear here once the market they are in resolves."
        />
      ) : (
        <div className="divide-y divide-slate-800">
          {settled.map((p) => (
            <div
              key={`${p.market_slug}-${p.outcome}-${p.resolved_at}`}
              className="p-4 flex items-center gap-4"
            >
              {/* Won or lost is the point of this list, so it is stated in
                  words as well as colour. */}
              <span
                className={cn(
                  'px-2 py-0.5 rounded text-xs font-medium shrink-0',
                  p.won
                    ? 'bg-green-500/10 text-green-400'
                    : 'bg-red-500/10 text-red-400'
                )}
              >
                {p.won ? 'Won' : 'Lost'}
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white truncate">{p.market_slug}</p>
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <span className="text-aware-400">{p.outcome}</span>
                  <span>·</span>
                  <span className="tabular-nums">
                    {formatNumber(p.shares, 0)} shares @ {cents(p.avg_entry_price)}
                  </span>
                  <span>·</span>
                  <span>{getTimeAgo(p.resolved_at)}</span>
                </div>
              </div>
              <p
                className={cn(
                  'text-sm font-medium tabular-nums shrink-0',
                  p.realized_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                )}
              >
                {p.realized_pnl >= 0 ? '+' : '\u2212'}
                {formatCurrency(Math.abs(p.realized_pnl))}
              </p>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

function HistoryCard({
  activity,
  pending,
}: {
  activity: TraderActivity | null
  pending: boolean
}) {
  const trades = activity?.recent_trades ?? []

  return (
    <Panel title="Recent trades" caption="Latest fills observed on Polymarket for this wallet.">
      {pending ? (
        <SkeletonRows rows={5} />
      ) : trades.length === 0 ? (
        <Empty title="No trades recorded for this wallet yet" />
      ) : (
        <div className="divide-y divide-slate-800">
          {trades.map((trade) => (
            <div key={`${trade.ts}-${trade.market_slug}-${trade.outcome}-${trade.price}`} className="p-4 flex items-center gap-4">
              <div
                className={cn(
                  'p-2 rounded-lg shrink-0',
                  trade.side === 'BUY' ? 'bg-green-500/10' : 'bg-red-500/10'
                )}
              >
                {trade.side === 'BUY' ? (
                  <TrendingUp className="h-4 w-4 text-green-400" />
                ) : (
                  <TrendingDown className="h-4 w-4 text-red-400" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white truncate">{trade.title}</p>
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <span className={trade.side === 'BUY' ? 'text-green-400' : 'text-red-400'}>
                    {trade.side}
                  </span>
                  <span>•</span>
                  <span className="truncate">{trade.outcome}</span>
                  <span>•</span>
                  <span className="shrink-0">{getTimeAgo(trade.ts)}</span>
                </div>
              </div>
              <div className="text-right shrink-0">
                <p className="text-sm font-medium text-white tabular-nums">
                  {formatCurrency(trade.notional)}
                </p>
                <p className="text-xs text-slate-500 tabular-nums">@ {cents(trade.price)}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

function StatBox({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string
  value: string
  icon: any
  color: string
}) {
  return (
    <div className="rounded-lg bg-slate-800/50 p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon className={cn('h-4 w-4', color)} />
        <span className="text-xs text-slate-500">{label}</span>
      </div>
      <p className="text-xl font-bold text-white">{value}</p>
    </div>
  )
}
