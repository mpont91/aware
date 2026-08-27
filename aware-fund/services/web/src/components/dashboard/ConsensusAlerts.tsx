'use client'

import { useEffect, useState } from 'react'
import {
  CONSENSUS_LOOKBACK_HOURS,
  CONSENSUS_MIN_TRADERS,
  CONSENSUS_MIN_VOLUME,
} from '@/lib/consensus'
import Link from 'next/link'
import { Users, ArrowRight, Zap } from 'lucide-react'
import { cn } from '@/lib/utils'
import { api, ConsensusSignal } from '@/lib/api'


const strengthColors: Record<string, string> = {
  STRONG: 'bg-green-500/20 text-green-400 border-green-500/30',
  MODERATE: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  WEAK: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
}

export function ConsensusAlerts() {
  const [signals, setSignals] = useState<ConsensusSignal[]>([])
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    // Same thresholds as the dedicated page, so both agree on what counts as
    // a signal instead of the dashboard showing more than the page behind it.
    api
      .getConsensusSignals(
        CONSENSUS_MIN_TRADERS,
        CONSENSUS_MIN_VOLUME,
        CONSENSUS_LOOKBACK_HOURS
      )
      .then((res) => {
        if (!cancelled) setSignals(res.signals.slice(0, 3))
      })
      .catch(() => {
        if (!cancelled) setSignals([])
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="rounded-xl bg-slate-900/50 border border-slate-800 overflow-hidden h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-5 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-purple-500/10 p-2">
            <Users className="h-5 w-5 text-purple-400" />
          </div>
          <div>
            <h3 className="font-semibold text-white">Consensus Signals</h3>
            <p className="text-xs text-slate-500">Smart money alignment</p>
          </div>
        </div>
        <Link
          href="/consensus"
          className="text-sm text-aware-400 hover:text-aware-300 transition-colors"
        >
          View all
        </Link>
      </div>

      {/* Signals List */}
      <div className="divide-y divide-slate-800">
        {isLoading ? (
          <p className="p-4 text-sm text-slate-500">Loading…</p>
        ) : signals.length === 0 ? (
          <p className="p-4 text-sm text-slate-500">
            No consensus signals yet. They appear once several high-scoring
            traders back the same outcome in the same market.
          </p>
        ) : (
          signals.map((signal) => (
            <div
              key={signal.market_slug}
              className="p-4 hover:bg-slate-800/50 transition-colors"
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <p className="text-sm text-white font-medium leading-tight line-clamp-2">
                  {signal.title || signal.market_slug}
                </p>
                <span
                  className={cn(
                    'shrink-0 px-2 py-0.5 text-xs font-medium rounded border',
                    strengthColors[signal.consensus_strength]
                  )}
                >
                  {signal.consensus_strength}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-1">
                    <Zap className="h-3.5 w-3.5 text-aware-400" />
                    <span className="text-sm font-semibold text-aware-400">
                      {signal.favored_outcome}
                    </span>
                  </div>
                  <span className="text-xs text-slate-500">
                    {signal.trader_count} trader{signal.trader_count === 1 ? '' : 's'}
                  </span>
                </div>

                <span className="text-xs font-medium text-slate-400 tabular-nums">
                  ${signal.total_volume.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </span>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Footer */}
      <div className="p-4 bg-slate-800/30">
        <Link
          href="/consensus"
          className="flex items-center justify-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"
        >
          See all consensus signals
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    </div>
  )
}
