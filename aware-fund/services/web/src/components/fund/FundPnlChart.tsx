'use client'

import { useState, useEffect } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
} from 'recharts'
import { Loader2 } from 'lucide-react'
import { apiDate, cn, formatCurrency } from '@/lib/utils'
import { api, FundPnlHistory } from '@/lib/api'

interface FundPnlChartProps {
  fundId: string
  height?: number
  showControls?: boolean
  className?: string
}

const timeRanges = [
  { label: '1W', days: 7 },
  { label: '1M', days: 30 },
  { label: '3M', days: 90 },
  { label: 'ALL', days: 365 },
]

export function FundPnlChart({
  fundId,
  height = 300,
  showControls = true,
  className,
}: FundPnlChartProps) {
  const [data, setData] = useState<FundPnlHistory['points']>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedRange, setSelectedRange] = useState(30)

  // Fetch NAV history
  useEffect(() => {
    async function fetchData() {
      setIsLoading(true)
      setError(null)
      try {
        // P&L rather than NAV: nav_per_share is 1.0 at every point for every
        // fund, since the NAV calculation has no deposits or positions to
        // work from. This charts what the fund actually made.
        const response = await api.getFundPnlHistory(fundId, selectedRange)
        setData(response?.points || [])
      } catch (err) {
        console.error('Failed to fetch fund P&L history:', err)
        setError('Failed to load chart data')
        setData([])
      } finally {
        setIsLoading(false)
      }
    }

    fetchData()
  }, [fundId, selectedRange])

  // Format data for chart
  const chartData = (data || []).map(point => ({
    date: apiDate(point.timestamp).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    }),
    fullDate: apiDate(point.timestamp).toLocaleDateString('en-US', {
      month: 'long',
      day: 'numeric',
      year: 'numeric',
    }),
    // Cumulative P&L at that moment, in dollars.
    nav: point.total_pnl,
    realized: point.realized_pnl,
    unrealized: point.unrealized_pnl,
  }))

  // Change across the visible window, in dollars: a percentage would need a
  // capital base, and the fund's deployed capital moves as positions rotate.
  const firstPnl = data[0]?.total_pnl ?? 0
  const lastPnl = data[data.length - 1]?.total_pnl ?? 0
  const changeUsd = lastPnl - firstPnl
  const isPositive = changeUsd >= 0

  // Custom tooltip
  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload?.[0]) return null

    const item = payload[0].payload
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-lg shadow-xl p-3">
        <p className="text-slate-400 text-xs mb-1">{item.fullDate}</p>
        <p className="text-white font-semibold">
          P&L: {formatCurrency(item.nav)}
        </p>
        {/* Realised is settled; unrealised still moves with the market. */}
        <p className="text-xs text-slate-400 mt-1">
          {formatCurrency(item.realized)} realized
          {' · '}
          {formatCurrency(item.unrealized)} unrealized
        </p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div
        className={cn('flex items-center justify-center bg-slate-900/50 rounded-xl', className)}
        style={{ height }}
      >
        <Loader2 className="w-6 h-6 text-aware-400 animate-spin" />
        <span className="ml-2 text-slate-400">Loading chart...</span>
      </div>
    )
  }

  if (error || data.length === 0) {
    return (
      <div
        className={cn('flex items-center justify-center bg-slate-900/50 rounded-xl text-slate-400', className)}
        style={{ height }}
      >
        {error || 'No data available'}
      </div>
    )
  }

  return (
    <div className={cn('space-y-4', className)}>
      {/* Controls */}
      {showControls && (
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {timeRanges.map((range) => (
              <button
                key={range.days}
                onClick={() => setSelectedRange(range.days)}
                className={cn(
                  'px-3 py-1.5 text-sm font-medium rounded-lg transition-all',
                  selectedRange === range.days
                    ? 'bg-aware-500/20 text-aware-400 ring-1 ring-aware-500/50'
                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                )}
              >
                {range.label}
              </button>
            ))}
          </div>

        </div>
      )}

      {/* Chart */}
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id={`navGradient-${fundId}`} x1="0" y1="0" x2="0" y2="1">
                <stop
                  offset="5%"
                  stopColor={isPositive ? '#22c55e' : '#ef4444'}
                  stopOpacity={0.3}
                />
                <stop
                  offset="95%"
                  stopColor={isPositive ? '#22c55e' : '#ef4444'}
                  stopOpacity={0}
                />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis
              dataKey="date"
              stroke="#64748b"
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              stroke="#64748b"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => `$${value.toFixed(2)}`}
              domain={['dataMin - 0.1', 'dataMax + 0.1']}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="nav"
              stroke={isPositive ? '#22c55e' : '#ef4444'}
              strokeWidth={2}
              fill={`url(#navGradient-${fundId})`}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
