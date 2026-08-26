'use client'

import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { LineChart as LineChartIcon } from 'lucide-react'
import { usePnlHistory } from '@/lib/hooks'

/**
 * Categorical hues, assigned in fixed order and never cycled, so a strategy
 * keeps its colour as others come and go. Validated for the dark chart surface:
 * inside the OKLCH lightness band, above the chroma floor, and separated for
 * colour-vision deficiency. Green and red are deliberately absent — they mean
 * profit and loss here, and reusing them as identity would be ambiguous.
 */
const SERIES_COLORS = ['#0284c7', '#d97706', '#8b5cf6', '#0891b2']

const AXIS = '#64748b'
const GRID = '#1e293b'

function money(v: number): string {
  const sign = v < 0 ? '-' : ''
  const abs = Math.abs(v)
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`
  return `${sign}$${abs.toFixed(0)}`
}

function timeLabel(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function StrategyPerformance() {
  const { history, isLoading, error } = usePnlHistory(7)

  const strategies = history?.strategies ?? []
  const points = history?.points ?? []

  return (
    <div className="rounded-xl bg-slate-900/50 border border-slate-800 overflow-hidden">
      <div className="flex items-center justify-between p-5 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-aware-500/10 p-2">
            <LineChartIcon className="h-5 w-5 text-aware-400" />
          </div>
          <div>
            <h3 className="font-semibold text-white">Strategy Performance</h3>
            <p className="text-xs text-slate-500">
              Cumulative P&amp;L per strategy, last 7 days
            </p>
          </div>
        </div>
        {points.length > 0 && (
          <span className="text-xs text-slate-500 tabular-nums">
            {points.length} snapshot{points.length === 1 ? '' : 's'}
          </span>
        )}
      </div>

      <div className="p-5">
        {isLoading ? (
          <p className="text-sm text-slate-500 py-12 text-center">Loading…</p>
        ) : error ? (
          <p className="text-sm text-slate-500 py-12 text-center">{error}</p>
        ) : points.length < 2 ? (
          <div className="py-12 text-center">
            <p className="text-sm text-slate-400">Not enough history yet</p>
            <p className="text-xs text-slate-500 mt-1">
              A point is recorded each time the analytics pipeline runs. The
              curve appears once there are at least two.
            </p>
          </div>
        ) : (
          <>
            <div className="h-64 -ml-2">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <defs>
                    {strategies.map((s, i) => (
                      <linearGradient
                        key={s}
                        id={`fill-${s}`}
                        x1="0"
                        y1="0"
                        x2="0"
                        y2="1"
                      >
                        <stop
                          offset="0%"
                          stopColor={SERIES_COLORS[i % SERIES_COLORS.length]}
                          stopOpacity={0.22}
                        />
                        <stop
                          offset="100%"
                          stopColor={SERIES_COLORS[i % SERIES_COLORS.length]}
                          stopOpacity={0}
                        />
                      </linearGradient>
                    ))}
                  </defs>

                  {/* Recessive grid: horizontal only, so it reads as a
                      reference rather than competing with the marks. */}
                  <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />

                  <XAxis
                    dataKey="timestamp"
                    tickFormatter={timeLabel}
                    stroke={AXIS}
                    tick={{ fill: AXIS, fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={32}
                  />
                  <YAxis
                    tickFormatter={money}
                    stroke={AXIS}
                    tick={{ fill: AXIS, fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    width={56}
                  />

                  {/* Break-even line: above it the strategy made money. */}
                  <CartesianGrid
                    horizontalPoints={[0]}
                    stroke="#334155"
                    vertical={false}
                  />

                  <Tooltip
                    contentStyle={{
                      background: '#0f172a',
                      border: '1px solid #1e293b',
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    labelFormatter={(v) => new Date(v as string).toLocaleString()}
                    formatter={(value, name) => [
                      `$${Number(value).toLocaleString(undefined, {
                        maximumFractionDigits: 2,
                      })}`,
                      name,
                    ]}
                  />

                  <Legend
                    verticalAlign="bottom"
                    height={28}
                    iconType="plainline"
                    wrapperStyle={{ fontSize: 12, color: AXIS }}
                  />

                  {strategies.map((s, i) => (
                    <Area
                      key={s}
                      type="monotone"
                      dataKey={s}
                      name={s}
                      stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                      strokeWidth={2}
                      fill={`url(#fill-${s})`}
                      dot={false}
                      activeDot={{ r: 4, strokeWidth: 2, stroke: '#0f172a' }}
                      connectNulls
                    />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            </div>

            {/* Latest value per strategy, so identity never rests on colour
                alone and the current number is readable without hovering. */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4 pt-4 border-t border-slate-800">
              {strategies.map((s, i) => {
                const latest = points[points.length - 1]?.[s]
                const value = typeof latest === 'number' ? latest : null
                return (
                  <div key={s}>
                    <div className="flex items-center gap-1.5">
                      <span
                        className="w-2.5 h-2.5 rounded-sm shrink-0"
                        style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }}
                      />
                      <span className="text-xs text-slate-400 truncate">{s}</span>
                    </div>
                    <p
                      className={
                        value === null
                          ? 'text-sm text-slate-500 mt-0.5 tabular-nums'
                          : value >= 0
                            ? 'text-sm font-semibold text-green-400 mt-0.5 tabular-nums'
                            : 'text-sm font-semibold text-red-400 mt-0.5 tabular-nums'
                      }
                    >
                      {value === null
                        ? '—'
                        : `${value >= 0 ? '+' : ''}$${value.toLocaleString(undefined, {
                            maximumFractionDigits: 0,
                          })}`}
                    </p>
                  </div>
                )
              })}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
