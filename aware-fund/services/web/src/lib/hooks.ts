'use client'

import { useCallback, useEffect, useState } from 'react'
import { api, DataFreshness, PnlSummary } from '@/lib/api'

interface DataFreshnessState {
  freshness: DataFreshness | null
  isLoading: boolean
  error: string | null
  refetch: () => Promise<void>
}

export function useDataFreshness(refreshIntervalMs = 30000): DataFreshnessState {
  const [freshness, setFreshness] = useState<DataFreshness | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchFreshness = useCallback(async () => {
    try {
      setError(null)
      const data = await api.getDataFreshness()
      setFreshness(data)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load data freshness'
      setError(msg)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    setIsLoading(true)
    fetchFreshness()

    const interval = setInterval(fetchFreshness, refreshIntervalMs)
    return () => clearInterval(interval)
  }, [fetchFreshness, refreshIntervalMs])

  return {
    freshness,
    isLoading,
    error,
    refetch: fetchFreshness,
  }
}


interface PnlSummaryState {
  pnl: PnlSummary | null
  isLoading: boolean
  error: string | null
  refetch: () => Promise<void>
}

/** Paper-trading P&L. Refreshes on a slow interval: the analytics job only
 *  writes a new snapshot once per pipeline run. */
export function usePnlSummary(refreshIntervalMs = 60000): PnlSummaryState {
  const [pnl, setPnl] = useState<PnlSummary | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchPnl = useCallback(async () => {
    try {
      setError(null)
      const data = await api.getPnlSummary()
      setPnl(data)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load P&L'
      setError(msg)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    setIsLoading(true)
    fetchPnl()

    const interval = setInterval(fetchPnl, refreshIntervalMs)
    return () => clearInterval(interval)
  }, [fetchPnl, refreshIntervalMs])

  return { pnl, isLoading, error, refetch: fetchPnl }
}
