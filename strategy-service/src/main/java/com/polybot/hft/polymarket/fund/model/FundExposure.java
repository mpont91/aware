package com.polybot.hft.polymarket.fund.model;

import org.slf4j.Logger;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Map;

/**
 * Ceiling on how much of its capital one fund may have committed at once.
 *
 * The per-position, per-market and per-day limits each bound a single trade or
 * a single session. None of them bounded the sum, so nothing stopped a fund
 * from committing more than the capital it was allocated.
 */
public final class FundExposure {

    /**
     * Warn once the fund passes this share of its capital, well before the cap
     * binds, so it is visible building up rather than only when trading stops.
     */
    private static final double WARN_PCT = 0.60;

    private FundExposure() {
    }

    /**
     * Whether committing {@code addedCost} more keeps the fund inside its cap.
     *
     * Measured on cost basis rather than mark value: the cap is about capital
     * committed, which is the cash that went out, and a mark-based figure would
     * move the ceiling around as prices do.
     */
    public static boolean isWithinCap(
            String fundName,
            Map<String, FundPosition> positions,
            BigDecimal addedCost,
            BigDecimal capital,
            double maxExposurePct,
            Logger log
    ) {
        if (capital == null || capital.compareTo(BigDecimal.ZERO) <= 0) {
            return true;
        }

        BigDecimal committed = BigDecimal.ZERO;
        for (FundPosition p : positions.values()) {
            committed = committed.add(p.shares().multiply(p.avgCostBasis()));
        }

        BigDecimal proposed = committed.add(addedCost == null ? BigDecimal.ZERO : addedCost);
        BigDecimal cap = capital.multiply(BigDecimal.valueOf(maxExposurePct));

        if (proposed.compareTo(cap) > 0) {
            log.warn("{}: exposure ${} would exceed the ${} cap ({}% of ${} capital); "
                            + "no new positions until some settle",
                    fundName,
                    proposed.setScale(2, RoundingMode.HALF_UP),
                    cap.setScale(2, RoundingMode.HALF_UP),
                    Math.round(maxExposurePct * 100),
                    capital);
            return false;
        }

        BigDecimal warnAt = capital.multiply(BigDecimal.valueOf(WARN_PCT));
        if (proposed.compareTo(warnAt) > 0 && committed.compareTo(warnAt) <= 0) {
            log.warn("{}: exposure passed {}% of capital (${} of ${})",
                    fundName, Math.round(WARN_PCT * 100),
                    proposed.setScale(2, RoundingMode.HALF_UP), capital);
        }
        return true;
    }
}
