package com.polybot.hft.executor.portfolio;

import com.polybot.hft.executor.sim.ExecutorSimulationProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

/**
 * Values the paper account the way the live one is valued.
 *
 * In simulation the bankroll endpoint answered zero for cash, equity and
 * position counts. Everything that consumes a balance — the dynamic sizing,
 * the circuit breaker that stops trading when the bankroll runs low — was
 * therefore untestable: it would run for the first time on the day real money
 * was behind it, which is the worst possible day for a first run.
 *
 * The figures come from the marked positions the analytics P&L job writes,
 * which are built from the simulator's own fills, so paper and live are valued
 * from the same idea of what a position is worth.
 *
 * <p>The accounting, where C is the cost basis of everything ever bought and R
 * is what settled markets paid back:
 *
 * <pre>
 *   cash   = starting - C + R
 *          = starting - (cost of open positions) + (realized P&L)
 *   equity = cash + (market value of open positions)
 * </pre>
 *
 * The second form is what this computes, because both of its terms are columns
 * on the positions table.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class PaperBankrollCalculator {

    private static final HttpClient HTTP =
            HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();

    /**
     * Positions the job could not mark are left out of the equity. Their cost
     * still counts against cash — the money did leave — but valuing them at a
     * price hours out of date would put invented equity on the books.
     */
    private static final String QUERY = """
            SELECT
                sumIf(cost_usd, is_resolved = 0) AS open_cost,
                sumIf(value_usd, is_resolved = 0 AND mark_status != 'STALE') AS open_value,
                sumIf(pnl_usd, is_resolved = 1) AS realized_pnl,
                countIf(is_resolved = 0) AS open_positions,
                countIf(is_resolved = 1) AS settled_positions
            FROM polybot.aware_strategy_pnl_positions
            WHERE calculated_at = (
                SELECT max(calculated_at) FROM polybot.aware_strategy_pnl_positions
            )
            FORMAT TabSeparated
            """;

    private final ExecutorSimulationProperties sim;

    /** The paper book, or the untouched starting capital if it cannot be read. */
    public PaperBook read() {
        BigDecimal starting = sim.startingBankrollUsd();
        String body = query();
        if (body == null || body.isBlank()) {
            return new PaperBook(starting, starting, BigDecimal.ZERO, 0, 0);
        }

        String[] cols = body.trim().split("\t");
        if (cols.length < 5) {
            log.debug("Unexpected paper bankroll row: {}", body);
            return new PaperBook(starting, starting, BigDecimal.ZERO, 0, 0);
        }

        try {
            BigDecimal openCost = new BigDecimal(cols[0]);
            BigDecimal openValue = new BigDecimal(cols[1]);
            BigDecimal realized = new BigDecimal(cols[2]);
            int open = Integer.parseInt(cols[3]);
            int settled = Integer.parseInt(cols[4]);

            BigDecimal cash = starting.subtract(openCost).add(realized);
            BigDecimal equity = cash.add(openValue);
            return new PaperBook(
                    cash.setScale(6, RoundingMode.HALF_UP),
                    equity.setScale(6, RoundingMode.HALF_UP),
                    openValue.setScale(6, RoundingMode.HALF_UP),
                    open,
                    settled);
        } catch (NumberFormatException e) {
            log.debug("Could not parse paper bankroll row '{}': {}", body, e.getMessage());
            return new PaperBook(starting, starting, BigDecimal.ZERO, 0, 0);
        }
    }

    private String query() {
        try {
            String base = sim.tradeTapeClickhouseUrl();
            if (base == null || base.isBlank()) {
                return null;
            }
            if (base.endsWith("/")) {
                base = base.substring(0, base.length() - 1);
            }

            StringBuilder q = new StringBuilder("database=")
                    .append(URLEncoder.encode(sim.tradeTapeClickhouseDatabase(), StandardCharsets.UTF_8));
            String user = sim.tradeTapeClickhouseUser();
            String password = sim.tradeTapeClickhousePassword();
            if (user != null && !user.isBlank()) {
                q.append("&user=").append(URLEncoder.encode(user.trim(), StandardCharsets.UTF_8));
            }
            if (password != null && !password.isBlank()) {
                q.append("&password=").append(URLEncoder.encode(password, StandardCharsets.UTF_8));
            }

            HttpRequest req = HttpRequest.newBuilder(URI.create(base + "/?" + q))
                    .timeout(Duration.ofSeconds(5))
                    .header("Content-Type", "text/plain; charset=utf-8")
                    .POST(HttpRequest.BodyPublishers.ofString(QUERY))
                    .build();

            HttpResponse<String> resp = HTTP.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() != 200) {
                log.debug("Paper bankroll query failed status={} body={}", resp.statusCode(), resp.body());
                return null;
            }
            return resp.body();
        } catch (Exception e) {
            log.debug("Paper bankroll query error: {}", e.getMessage());
            return null;
        }
    }

    /** Cash, total equity and what is still open, for the paper account. */
    public record PaperBook(
            BigDecimal cashUsd,
            BigDecimal equityUsd,
            BigDecimal openValueUsd,
            int openPositions,
            int settledPositions
    ) {
    }
}
