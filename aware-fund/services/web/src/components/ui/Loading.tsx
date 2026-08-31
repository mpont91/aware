'use client'

import { cn } from '@/lib/utils'

interface LoadingProps {
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

export function Loading({ size = 'md', className }: LoadingProps) {
  const sizeClasses = {
    sm: 'h-4 w-4',
    md: 'h-8 w-8',
    lg: 'h-12 w-12',
  }

  return (
    <div className={cn('flex items-center justify-center', className)}>
      <div
        className={cn(
          'animate-spin rounded-full border-2 border-slate-700 border-t-aware-500',
          sizeClasses[size]
        )}
      />
    </div>
  )
}

export function LoadingCard() {
  return (
    <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-6 animate-pulse">
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-full bg-slate-800" />
        <div className="flex-1 space-y-2">
          <div className="h-4 bg-slate-800 rounded w-3/4" />
          <div className="h-3 bg-slate-800 rounded w-1/2" />
        </div>
      </div>
      <div className="mt-4 space-y-2">
        <div className="h-3 bg-slate-800 rounded" />
        <div className="h-3 bg-slate-800 rounded w-5/6" />
      </div>
    </div>
  )
}

export function LoadingTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="rounded-xl bg-slate-900/50 border border-slate-800 overflow-hidden">
      <div className="p-4 border-b border-slate-800">
        <div className="h-5 bg-slate-800 rounded w-1/4 animate-pulse" />
      </div>
      <div className="divide-y divide-slate-800">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="p-4 flex items-center gap-4 animate-pulse">
            <div className="w-8 h-8 rounded-full bg-slate-800" />
            <div className="flex-1 space-y-2">
              <div className="h-4 bg-slate-800 rounded w-1/3" />
              <div className="h-3 bg-slate-800 rounded w-1/4" />
            </div>
            <div className="h-4 bg-slate-800 rounded w-16" />
            <div className="h-4 bg-slate-800 rounded w-20" />
          </div>
        ))}
      </div>
    </div>
  )
}

export function LoadingPage() {
  return (
    <div className="space-y-6">
      {/* Header skeleton */}
      <div className="animate-pulse">
        <div className="h-8 bg-slate-800 rounded w-1/4 mb-2" />
        <div className="h-4 bg-slate-800 rounded w-1/3" />
      </div>

      {/* Stats grid skeleton */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-xl bg-slate-900/50 border border-slate-800 p-5 animate-pulse">
            <div className="h-4 bg-slate-800 rounded w-1/2 mb-3" />
            <div className="h-8 bg-slate-800 rounded w-3/4" />
          </div>
        ))}
      </div>

      {/* Main content skeleton */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <LoadingCard />
        <LoadingCard />
      </div>
    </div>
  )
}

/**
 * Placeholders shaped like the content they stand in for.
 *
 * A figure rendered as 0 while its request is in flight is indistinguishable
 * from a figure that is genuinely 0, and this dashboard is mostly figures: the
 * P&L, the position counts, the fund returns. Every one of them defaulted to
 * zero and then jumped. A placeholder says "not yet" in a way a number cannot.
 *
 * Each of these matches the height of what replaces it, so nothing moves when
 * the data lands. Animation is dropped for anyone who has asked for less of it.
 */
const SHIMMER = 'animate-pulse motion-reduce:animate-none bg-slate-800 rounded'

/** One block. Size it with className, or with style for a computed height. */
export function Skeleton({
  className,
  style,
}: {
  className?: string
  style?: React.CSSProperties
}) {
  return <div className={cn(SHIMMER, className)} style={style} aria-hidden="true" />
}

/** A line of body text. */
export function SkeletonText({ width = 'w-24', className }: { width?: string; className?: string }) {
  return <Skeleton className={cn('h-4', width, className)} />
}

/** A headline figure — the big number on a stat tile. */
export function SkeletonValue({ width = 'w-28', className }: { width?: string; className?: string }) {
  return <Skeleton className={cn('h-8', width, className)} />
}

/** Rows of a list, without the card around them. */
export function SkeletonRows({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('divide-y divide-slate-800', className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="p-4 flex items-center gap-4">
          <Skeleton className="w-8 h-8 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-3 w-1/4" />
          </div>
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  )
}

/** The plot area of a chart, so the card keeps its height. */
export function SkeletonChart({ height = 300 }: { height?: number }) {
  return (
    <div className="flex items-end gap-2 px-2" style={{ height }} aria-hidden="true">
      {[45, 70, 55, 85, 60, 90, 75, 50, 80, 65, 95, 70].map((h, i) => (
        <Skeleton key={i} className="flex-1" style={{ height: `${h}%` }} />
      ))}
    </div>
  )
}

/** A stat tile: label above, figure below. */
export function SkeletonStatCard() {
  return (
    <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-5">
      <div className="flex items-center gap-3 mb-3">
        <Skeleton className="w-9 h-9 rounded-lg" />
        <SkeletonText width="w-24" className="h-3" />
      </div>
      <SkeletonValue />
    </div>
  )
}
