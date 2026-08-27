import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

function toFiniteNumber(value: unknown, fallback = 0): number {
  const num = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(num) ? num : fallback
}

export function formatCurrency(value: unknown, maxFractionDigits = 2): string {
  const amount = toFiniteNumber(value, 0)
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: maxFractionDigits,
  }).format(amount)
}

export function formatNumber(value: unknown, maximumFractionDigits = 1): string {
  const num = toFiniteNumber(value, 0)
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits,
  }).format(num)
}

export function formatPercent(value: unknown, maximumFractionDigits = 1): string {
  const num = toFiniteNumber(value, 0)
  const sign = num > 0 ? '+' : ''
  return `${sign}${num.toFixed(maximumFractionDigits)}%`
}

/**
 * Parse a timestamp coming from the API.
 *
 * The API stamps UTC, but a bare ISO-8601 string with no offset is parsed by
 * JavaScript as *local* time, which silently shifts every reading by the
 * viewer's own offset — in Madrid that made a trade from a minute ago read as
 * "2h ago". Anything without a zone marker is treated as UTC, which is what
 * the backend means.
 */
export function parseApiDate(
  input: string | number | Date | null | undefined
): Date | null {
  if (input === null || input === undefined || input === '') return null
  if (input instanceof Date) return Number.isNaN(input.getTime()) ? null : input
  if (typeof input === 'number') return new Date(input)

  // Only a datetime is ambiguous. A date-only string is already parsed as UTC
  // by the engine, and appending Z to it would make it unparseable.
  const hasTime = /\d{2}:\d{2}/.test(input)
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(input)
  const date = new Date(hasTime && !hasZone ? `${input}Z` : input)
  return Number.isNaN(date.getTime()) ? null : date
}

/** parseApiDate for formatting call sites: always returns a Date. */
export function apiDate(input: string | number | Date): Date {
  return parseApiDate(input) ?? new Date(input)
}

export function getTimeAgo(input: string | number | Date | null | undefined): string {
  if (!input) return 'Unknown'

  const date = parseApiDate(input)
  if (!date) return 'Unknown'

  const diffMs = Date.now() - date.getTime()
  const diffSec = Math.max(0, Math.floor(diffMs / 1000))

  if (diffSec < 10) return 'just now'
  if (diffSec < 60) return `${diffSec}s ago`

  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`

  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`

  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 30) return `${diffDay}d ago`

  const diffMonth = Math.floor(diffDay / 30)
  if (diffMonth < 12) return `${diffMonth}mo ago`

  const diffYear = Math.floor(diffMonth / 12)
  return `${diffYear}y ago`
}
