'use client'

import { useState, useEffect } from 'react'
import { Skeleton } from '@/components/ui/Loading'
import Link from 'next/link'
import {
  Trophy,
  Search,
  TrendingUp,
  TrendingDown,
  ChevronDown,
  ChevronUp,
  Crown,
  Loader2,
  AlertCircle,
} from 'lucide-react'
import { cn, formatCurrency, formatNumber } from '@/lib/utils'
import { api, LeaderboardSummary, Trader, traderName, traderInitial } from '@/lib/api'

const tiers = ['All', 'Diamond', 'Gold', 'Silver', 'Bronze']

const tierStyles: Record<string, { bg: string; text: string; glow: string }> = {
  Diamond: { bg: 'bg-gradient-to-r from-cyan-400 to-blue-400', text: 'text-slate-900', glow: 'shadow-cyan-500/30' },
  DIAMOND: { bg: 'bg-gradient-to-r from-cyan-400 to-blue-400', text: 'text-slate-900', glow: 'shadow-cyan-500/30' },
  Gold: { bg: 'bg-gradient-to-r from-yellow-400 to-amber-400', text: 'text-slate-900', glow: 'shadow-yellow-500/30' },
  GOLD: { bg: 'bg-gradient-to-r from-yellow-400 to-amber-400', text: 'text-slate-900', glow: 'shadow-yellow-500/30' },
  Silver: { bg: 'bg-gradient-to-r from-slate-300 to-slate-400', text: 'text-slate-900', glow: '' },
  SILVER: { bg: 'bg-gradient-to-r from-slate-300 to-slate-400', text: 'text-slate-900', glow: '' },
  Bronze: { bg: 'bg-gradient-to-r from-orange-400 to-amber-600', text: 'text-white', glow: '' },
  BRONZE: { bg: 'bg-gradient-to-r from-orange-400 to-amber-600', text: 'text-white', glow: '' },
}

// Helper to capitalize tier
const formatTier = (tier: string) => tier.charAt(0).toUpperCase() + tier.slice(1).toLowerCase()

// Placeholder rows on the table's own 12-column grid, so nothing shifts
// sideways when the real rows arrive. Twenty of them: six left most of the
// viewport empty, and the page jumped as it filled to a hundred.
function LeaderboardSkeleton({ rows = 20 }: { rows?: number }) {
  return (
    <div className="divide-y divide-slate-800" aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="grid grid-cols-12 gap-4 p-4 items-center">
          <div className="col-span-1 flex justify-center">
            <Skeleton className="h-4 w-5" />
          </div>
          <div className="col-span-3 flex items-center gap-2">
            <Skeleton className="w-9 h-9 rounded-full shrink-0" />
            <div className="min-w-0 flex-1 space-y-1.5">
              <Skeleton className="h-3.5 w-32" />
              <Skeleton className="h-3 w-14 rounded-full" />
            </div>
          </div>
          <div className="col-span-1 flex justify-end">
            <Skeleton className="h-4 w-7" />
          </div>
          <div className="col-span-2 flex justify-end">
            <Skeleton className="h-4 w-20" />
          </div>
          <div className="col-span-2 flex justify-end">
            <Skeleton className="h-4 w-12" />
          </div>
          <div className="col-span-1 flex justify-end">
            <Skeleton className="h-4 w-8" />
          </div>
          <div className="col-span-2 flex justify-end">
            <Skeleton className="h-4 w-14" />
          </div>
        </div>
      ))}
    </div>
  )
}

// Defined at module scope on purpose. As a function inside the page component
// its identity changed on every render, so React unmounted and remounted all
// five headers each time — the visible flicker this was meant to avoid.
function SortHeader({
  label,
  col,
  span,
  sortBy,
  sortDir,
  onSort,
}: {
  label: string
  col: SortKey
  span: number
  sortBy: SortKey
  sortDir: 'asc' | 'desc'
  onSort: (key: SortKey) => void
}) {
  const active = sortBy === col
  return (
    <div
      className={cn(
        'text-right cursor-pointer hover:text-white flex items-center justify-end gap-1 select-none',
        span === 1 ? 'col-span-1' : span === 2 ? 'col-span-2' : 'col-span-3',
        active && 'text-white',
      )}
      onClick={() => onSort(col)}
      role="button"
      aria-sort={active ? (sortDir === 'desc' ? 'descending' : 'ascending') : 'none'}
    >
      {label}
      {active &&
        (sortDir === 'desc' ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronUp className="h-4 w-4" />
        ))}
    </div>
  )
}

type SortKey =
  | 'smart_money_score'
  | 'total_pnl'
  | 'win_rate'
  | 'sharpe_ratio'
  | 'total_trades'

export default function LeaderboardPage() {
  const [traders, setTraders] = useState<Trader[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedTier, setSelectedTier] = useState('All')
  const [searchQuery, setSearchQuery] = useState('')
  const [sortBy, setSortBy] = useState<SortKey>('smart_money_score')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [summary, setSummary] = useState<LeaderboardSummary | null>(null)

  // Clicking the active column flips direction; clicking a new one starts
  // descending, which is what "top traders" means for every column here.
  const toggleSort = (key: SortKey) => {
    if (key === sortBy) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortBy(key)
      setSortDir('desc')
    }
  }

  // Counts and totals over every scored trader. Kept apart from the row fetch
  // on purpose: the rows are a filtered page of at most a hundred, and deriving
  // the counts from them is what made picking Gold report "Gold (100),
  // Silver (0)" regardless of the real distribution.
  useEffect(() => {
    let cancelled = false
    api
      .getLeaderboardSummary()
      .then((d) => { if (!cancelled) setSummary(d) })
      .catch(() => { if (!cancelled) setSummary(null) })
    return () => { cancelled = true }
  }, [])

  // Typing must not fire a request per keystroke.
  const [debouncedSearch, setDebouncedSearch] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(searchQuery.trim()), 300)
    return () => clearTimeout(t)
  }, [searchQuery])

  // Tier, sort and search all go to the server, so this refetches when any of
  // them changes. Sorting and filtering used to happen here over the hundred
  // rows already loaded, which answered a different question than the one the
  // header asked: "top by P&L" returned the best of the top hundred by score,
  // not the best of 14,923.
  useEffect(() => {
    let cancelled = false
    async function fetchLeaderboard() {
      try {
        setIsLoading(true)
        setError(null)
        const data = await api.getLeaderboard(
          100,
          selectedTier === 'All' ? undefined : selectedTier,
          sortBy,
          sortDir,
          debouncedSearch || undefined,
        )
        // A slow earlier request must not overwrite a newer one; with search
        // firing on a timer these do overlap.
        if (!cancelled) setTraders(data)
      } catch (err) {
        if (!cancelled) {
          setError('Failed to load leaderboard. Make sure the API server is running.')
          console.error('Leaderboard fetch error:', err)
        }
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    fetchLeaderboard()
    return () => { cancelled = true }
  }, [selectedTier, sortBy, sortDir, debouncedSearch])

  // Already sorted and filtered by the server.
  const filteredTraders = traders

  // Calculate stats
  // Over every scored trader, not the page on screen — otherwise the headline
  // totals changed every time a tier was selected.
  const stats = {
    diamondCount: summary?.tier_counts.DIAMOND ?? 0,
    totalPnl: summary?.total_pnl ?? 0,
    avgWinRate: summary?.avg_win_rate ?? 0,
    totalTrades: summary?.total_trades ?? 0,
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <Trophy className="h-7 w-7 text-yellow-400" />
            Leaderboard
          </h1>
          <p className="text-slate-400 mt-1">
            Top traders ranked by Smart Money Score
          </p>
        </div>

        {/* Search */}
        <div className="relative max-w-xs w-full">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search traders..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full h-10 pl-9 pr-4 bg-slate-900 border border-slate-800 rounded-lg text-sm text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-aware-500/50 focus:border-aware-500"
          />
        </div>
      </div>

      {/* Tier Filter */}
      <div className="flex flex-wrap items-center gap-2">
        {tiers.map((tier) => (
          <button
            key={tier}
            onClick={() => setSelectedTier(tier)}
            className={cn(
              'px-4 py-2 text-sm font-medium rounded-lg transition-all',
              selectedTier === tier
                ? 'bg-aware-500/20 text-aware-400 ring-1 ring-aware-500/50'
                : 'bg-slate-800/50 text-slate-400 hover:bg-slate-800 hover:text-white'
            )}
          >
            {tier}
            {tier !== 'All' && summary && (
              <span className="ml-2 text-xs text-slate-500">
                ({summary.tier_counts[
                  tier.toUpperCase() as keyof typeof summary.tier_counts
                ] ?? 0})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Error State */}
      {error && (
        <div className="rounded-xl bg-red-500/10 border border-red-500/30 p-6 flex items-center gap-4">
          <AlertCircle className="h-6 w-6 text-red-400" />
          <div>
            <p className="text-red-400 font-medium">{error}</p>
            <p className="text-sm text-slate-400 mt-1">
              Start the API server: <code className="bg-slate-800 px-2 py-0.5 rounded">cd aware-fund/services/api && uvicorn main:app --reload</code>
            </p>
          </div>
        </div>
      )}

      {/* Table. The header renders in both states: it used to live inside a
          block gated on !isLoading, next to a separate skeleton block, so
          every sort tore the whole table down and rebuilt it — the columns
          you had just clicked vanished under the cursor. */}
      {!error && (
        <div className="rounded-xl bg-slate-900/50 border border-slate-800 overflow-hidden">
          {/* Table Header */}
          <div className="grid grid-cols-12 gap-4 p-4 bg-slate-800/50 text-sm font-medium text-slate-400 border-b border-slate-800">
            {/* Not sortable: it *is* the score ranking, so sorting by it
                would duplicate the Score header. */}
            <div
              className="col-span-1 text-center cursor-help"
              title="Rank by Smart Money Score across all scored traders"
            >
              #
            </div>
            <div className="col-span-3">Trader</div>
            <SortHeader label="Score" col="smart_money_score" span={1}
                        sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
            <SortHeader label="Total P&L" col="total_pnl" span={2}
                        sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
            <SortHeader label="Win %" col="win_rate" span={2}
                        sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
            <SortHeader label="Sharpe" col="sharpe_ratio" span={1}
                        sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
            <SortHeader label="Trades" col="total_trades" span={2}
                        sortBy={sortBy} sortDir={sortDir} onSort={toggleSort} />
          </div>

          {isLoading && <LeaderboardSkeleton rows={20} />}

          {/* Empty State */}
          {!isLoading && filteredTraders.length === 0 && (
            <div className="p-12 text-center">
              <Trophy className="h-12 w-12 text-slate-600 mx-auto mb-4" />
              <p className="text-slate-400">No traders found</p>
              <p className="text-sm text-slate-500 mt-1">
                {/* The server does the filtering now, so an empty result no
                    longer means an empty table — it usually means the search
                    or tier matched nothing. */}
                {debouncedSearch || selectedTier !== 'All'
                  ? 'Try adjusting your search or tier filter'
                  : 'Run the scoring job to populate the leaderboard'}
              </p>
            </div>
          )}

          {/* Table Body */}
          <div className="divide-y divide-slate-800">
            {!isLoading && filteredTraders.map((trader) => {
              const tierStyle = tierStyles[trader.tier] || tierStyles['BRONZE']
              return (
                <Link
                  key={trader.proxy_address || trader.username}
                  href={`/traders/${trader.username || trader.proxy_address}`}
                  className="grid grid-cols-12 gap-4 p-4 items-center hover:bg-slate-800/30 transition-colors"
                >
                  {/* Standing in the Smart Money ranking, which is what the
                      crown and medals mean. Briefly this was the row's
                      position instead, and reversing the sort then crowned
                      the worst trader on the board. Keeping the real rank
                      also says something useful under other sorts: the top
                      trader by P&L sitting at #1304 is the point. */}
                  <div className="col-span-1 text-center">
                    {trader.rank === 1 && <Crown className="w-6 h-6 text-yellow-400 mx-auto" />}
                    {trader.rank === 2 && (
                      <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-slate-300/20 text-slate-300 font-bold">
                        2
                      </span>
                    )}
                    {trader.rank === 3 && (
                      <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-orange-500/20 text-orange-400 font-bold">
                        3
                      </span>
                    )}
                    {trader.rank > 3 && (
                      <span className="text-slate-500 font-medium">{trader.rank}</span>
                    )}
                  </div>

                  {/* Trader */}
                  <div className="col-span-3 flex items-center gap-2">
                    <div className="w-9 h-9 rounded-full bg-gradient-to-br from-aware-400 to-aware-600 flex items-center justify-center text-white font-bold text-sm">
                      {traderInitial(trader)}
                    </div>
                    <div className="min-w-0">
                      <p className="font-medium text-white text-sm truncate">{traderName(trader)}</p>
                      <span
                        className={cn(
                          'inline-flex px-1.5 py-0.5 text-[10px] font-medium rounded-full',
                          tierStyle.bg,
                          tierStyle.text,
                          tierStyle.glow
                        )}
                      >
                        {formatTier(trader.tier)}
                      </span>
                    </div>
                  </div>

                  {/* Score */}
                  <div className="col-span-1 text-right">
                    <span className="text-base font-bold text-white">
                      {(trader.smart_money_score || 0).toFixed(0)}
                    </span>
                  </div>

                  {/* Total P&L */}
                  <div className="col-span-2 text-right">
                    <span className={cn(
                      'font-semibold',
                      (trader.total_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'
                    )}>
                      {formatCurrency(trader.total_pnl || 0)}
                    </span>
                  </div>

                  {/* Win Rate */}
                  <div className="col-span-2 text-right">
                    <span className="text-white">
                      {((trader.win_rate || 0) * 100).toFixed(1)}%
                    </span>
                  </div>

                  {/* Sharpe. Zero means not computed: it needs 20 days of
                      resolved P&L and no trader has that yet. Showing "0.00"
                      would read as a measured result. */}
                  <div className="col-span-1 text-right">
                    {trader.sharpe_ratio ? (
                      <span className="text-slate-300">
                        {trader.sharpe_ratio.toFixed(2)}
                      </span>
                    ) : (
                      <span className="text-slate-600" title="Needs 20 days of resolved P&L">
                        —
                      </span>
                    )}
                  </div>

                  {/* Trades */}
                  <div className="col-span-2 text-right">
                    <span className="text-slate-400">
                      {formatNumber(trader.total_trades || 0, 0)}
                    </span>
                  </div>
                </Link>
              )
            })}
          </div>
        </div>
      )}

      {/* Stats Summary */}
      {!isLoading && !error && traders.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="rounded-lg bg-slate-800/50 p-4 text-center">
            <p className="text-3xl font-bold text-white">{stats.diamondCount}</p>
            <p className="text-sm text-cyan-400">Diamond Traders</p>
          </div>
          <div className="rounded-lg bg-slate-800/50 p-4 text-center">
            <p className="text-3xl font-bold text-white">{formatCurrency(stats.totalPnl)}</p>
            <p className="text-sm text-green-400">Combined P&L</p>
          </div>
          <div className="rounded-lg bg-slate-800/50 p-4 text-center">
            <p className="text-3xl font-bold text-white">{(stats.avgWinRate * 100).toFixed(1)}%</p>
            <p className="text-sm text-aware-400">Avg Win Rate</p>
          </div>
          <div className="rounded-lg bg-slate-800/50 p-4 text-center">
            <p className="text-3xl font-bold text-white">{formatNumber(stats.totalTrades, 0)}</p>
            <p className="text-sm text-slate-400">Total Trades</p>
          </div>
        </div>
      )}
    </div>
  )
}
