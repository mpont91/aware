'use client'

import { useState, useEffect } from 'react'
import { SkeletonStatCard, SkeletonText } from '@/components/ui/Loading'
import Link from 'next/link'
import {
  TrendingUp,
  Users,
  DollarSign,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  Loader2,
  AlertCircle,
  Brain,
  CheckCircle,
  AlertTriangle,
  XCircle,
} from 'lucide-react'
import { cn, formatNumber, formatCurrency, formatPercent } from '@/lib/utils'
import { StatsCard } from '@/components/dashboard/StatsCard'
import { TopTraders } from '@/components/dashboard/TopTraders'
import { RecentActivity } from '@/components/dashboard/RecentActivity'
import { StrategyPerformance } from '@/components/dashboard/StrategyPerformance'
import { PnlBanner } from '@/components/dashboard/PnlBanner'
import { ConsensusAlerts } from '@/components/dashboard/ConsensusAlerts'
import { api, DashboardStats, MLHealthResponse } from '@/lib/api'

interface DashboardData {
  stats: DashboardStats | null
  mlHealth: MLHealthResponse | null
  error: string | null
  isLoading: boolean
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData>({
    stats: null,
    mlHealth: null,
    error: null,
    isLoading: true,
  })

  useEffect(() => {
    async function fetchDashboardData() {
      try {
        // Fetch stats and ML health in parallel
        const [statsData, mlHealthData] = await Promise.allSettled([
          api.getDashboardStats(),
          api.getMLHealth(),
        ])

        setData({
          stats: statsData.status === 'fulfilled' ? statsData.value : null,
          mlHealth: mlHealthData.status === 'fulfilled' ? mlHealthData.value : null,
          error: null,
          isLoading: false,
        })
      } catch (err) {
        setData({
          stats: null,
                mlHealth: null,
          error: 'Failed to load dashboard data. Make sure the API server is running.',
          isLoading: false,
        })
        console.error('Dashboard fetch error:', err)
      }
    }
    fetchDashboardData()
  }, [])

  const { stats, mlHealth, error, isLoading } = data

  // Fallback values for display
  const displayStats = stats || {
    total_traders: 0,
    total_trades: 0,
    total_volume_usd: 0,
    trades_24h: 0,
    traders_24h: 0,
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-slate-400 mt-1">
            Real-time overview of smart money activity
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm text-slate-500">
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Activity className="w-4 h-4" />
          )}
          {isLoading ? <SkeletonText width="w-32" className="h-3" /> : 'Last updated: just now'}
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="rounded-xl bg-red-500/10 border border-red-500/30 p-4 flex items-center gap-3">
          <AlertCircle className="h-5 w-5 text-red-400 flex-shrink-0" />
          <div>
            <p className="text-red-400 text-sm font-medium">{error}</p>
            <p className="text-slate-500 text-xs mt-0.5">
              Run: <code className="bg-slate-800 px-1 rounded">cd aware-fund/services/api && uvicorn main:app --reload --port 8000</code>
            </p>
          </div>
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {isLoading ? (
          <>
            {/* Placeholders rather than the zeros these default to: a figure
                showing 0 while its request is in flight cannot be told apart
                from one that is genuinely 0. */}
            <SkeletonStatCard />
            <SkeletonStatCard />
            <SkeletonStatCard />
            <SkeletonStatCard />
          </>
        ) : (
        <>
        <StatsCard
          title="Tracked Traders"
          value={formatNumber(displayStats.total_traders, 0)}
          icon={Users}
          trend={displayStats.traders_24h > 0 ? { value: displayStats.traders_24h, isPositive: true, label: 'in the last 24h' } : undefined}
          description="With scored activity"
        />
        <StatsCard
          title="Total Trades"
          value={formatNumber(displayStats.total_trades, 0)}
          icon={Activity}
          trend={displayStats.trades_24h > 0 ? { value: displayStats.trades_24h, isPositive: true, label: 'in the last 24h' } : undefined}
          description="Ingested trades"
        />
        <StatsCard
          title="Trading Volume"
          value={formatCurrency(displayStats.total_volume_usd)}
          icon={DollarSign}
          description="Total notional"
        />
        <StatsCard
          title="24h Trades"
          value={formatNumber(displayStats.trades_24h, 0)}
          icon={TrendingUp}
          description="Last 24 hours"
        />
        </>
        )}
      </div>

      {/* Headline P&L */}
      <PnlBanner />

      {/* ML Status Row */}
      <div className="grid grid-cols-1 gap-4">
        {/* ML Status Indicator */}
        <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Brain className="w-5 h-5 text-purple-400" />
              <span className="text-sm font-medium text-slate-300">ML Pipeline</span>
            </div>
            <Link href="/admin/ml" className="text-xs text-aware-400 hover:text-aware-300">
              Details →
            </Link>
          </div>
          {mlHealth ? (
            <div className="flex items-center gap-3">
              <div className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-lg',
                mlHealth.status === 'healthy' ? 'bg-green-500/20' :
                mlHealth.status === 'degraded' ? 'bg-yellow-500/20' : 'bg-red-500/20'
              )}>
                {mlHealth.status === 'healthy' ? (
                  <CheckCircle className="w-4 h-4 text-green-400" />
                ) : mlHealth.status === 'degraded' ? (
                  <AlertTriangle className="w-4 h-4 text-yellow-400" />
                ) : (
                  <XCircle className="w-4 h-4 text-red-400" />
                )}
                <span className={cn(
                  'text-sm font-medium capitalize',
                  mlHealth.status === 'healthy' ? 'text-green-400' :
                  mlHealth.status === 'degraded' ? 'text-yellow-400' : 'text-red-400'
                )}>
                  {mlHealth.status}
                </span>
              </div>
              <div className="text-xs text-slate-500">
                <span className="font-mono">{mlHealth.model_version}</span>
                <span className="mx-2">·</span>
                <span>{formatNumber(mlHealth.traders_scored, 0)} scored</span>
              </div>
            </div>
          ) : (
            isLoading ? (
              <div className="space-y-2">
                <SkeletonText width="w-20" className="h-5" />
                <SkeletonText width="w-40" className="h-3" />
              </div>
            ) : (
              <div className="text-sm text-slate-500">Not available</div>
            )
          )}
        </div>
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Top Traders - Takes 2 columns */}
        <div className="lg:col-span-2">
          <TopTraders />
        </div>

        {/* Consensus Alerts */}
        <div>
          <ConsensusAlerts />
        </div>
      </div>

      {/* Secondary Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <StrategyPerformance />
        <RecentActivity />
      </div>
    </div>
  )
}
