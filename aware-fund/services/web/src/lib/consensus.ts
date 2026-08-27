/**
 * Consensus filter thresholds, shared by the dashboard widget and the
 * consensus page.
 *
 * The volume floor comes from the observed distribution: among markets where
 * three or more scored traders agree inside the window, combined notional runs
 * a median near $100 and tops out around $1.2k. The $5000 both callers used to
 * send excluded every market that has ever existed here, so the widget sat
 * empty. $250 is roughly the upper quartile.
 *
 * They live here rather than in either caller because they had already drifted
 * apart once: the page was lowered and the dashboard widget was not, so the
 * same signal list looked broken in one place and fine in the other.
 */
export const CONSENSUS_MIN_TRADERS = 3
export const CONSENSUS_MIN_VOLUME = 250
export const CONSENSUS_LOOKBACK_HOURS = 48
