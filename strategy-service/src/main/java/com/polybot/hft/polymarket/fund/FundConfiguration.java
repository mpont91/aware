package com.polybot.hft.polymarket.fund;

import com.polybot.hft.config.HftProperties;
import com.polybot.hft.polymarket.fund.config.FundConfig;
import com.polybot.hft.polymarket.fund.model.FundType;
import com.polybot.hft.polymarket.fund.service.FundPositionMirror;
import com.polybot.hft.polymarket.fund.service.FundRegistry;
import com.polybot.hft.polymarket.fund.service.FundTradeListener;
import com.polybot.hft.polymarket.fund.service.IndexWeightProvider;
import com.polybot.hft.strategy.executor.ExecutorApiClient;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;

import java.time.Clock;

/**
 * Spring configuration for AWARE Fund components.
 *
 * Enabled when hft.fund.enabled=true.
 *
 * Wires up:
 * - FundConfig from HftProperties.Fund
 * - IndexWeightProvider for PSI index weights
 * - FundPositionMirror for trade execution
 * - FundTradeListener for Kafka consumption
 * - Scheduled task for processing pending signals
 */
@Slf4j
@Configuration
@EnableScheduling
@ConditionalOnProperty(prefix = "hft.fund", name = "enabled", havingValue = "true")
public class FundConfiguration {

    @Bean
    public FundConfig fundConfig(HftProperties properties) {
        FundConfig config = FundConfig.from(properties.fund());
        log.info("Fund configuration loaded: index={}, capital=${}, enabled={}",
                config.indexType(), config.capitalUsd(), config.enabled());
        return config;
    }

    /**
     * The registry itself is shared, so this bean exists either way. The
     * single-fund registration below does not: when multi-fund mode is on it
     * owns the roster, and registering hft.fund.index-type here as well threw
     * "Fund already registered" and left the registry holding this block's
     * capital for a fund the multi-fund allocation had sized differently.
     */
    @Bean
    public FundRegistry fundRegistry(
            FundConfig config,
            @Value("${hft.multi-fund.enabled:false}") boolean multiFundEnabled
    ) {
        FundRegistry registry = new FundRegistry();

        if (multiFundEnabled) {
            log.info("Multi-fund mode is on; skipping single-fund registration of {}",
                    config.indexType());
            return registry;
        }

        // Register the configured fund on startup
        if (config.enabled()) {
            try {
                FundType fundType = FundType.fromId(config.indexType());
                registry.registerFund(config.indexType(), fundType, config.capitalUsd());
                log.info("Registered fund {} ({}) with ${} capital",
                        config.indexType(), fundType.getStrategy(), config.capitalUsd());
            } catch (IllegalArgumentException e) {
                log.warn("Unknown fund type '{}', skipping registration", config.indexType());
            }
        }

        return registry;
    }

    @Bean
    public IndexWeightProvider indexWeightProvider(JdbcTemplate jdbcTemplate) {
        return new IndexWeightProvider(jdbcTemplate);
    }

    @Bean
    public FundPositionMirror fundPositionMirror(
            FundConfig config,
            IndexWeightProvider weightProvider,
            ExecutorApiClient executorApi,
            JdbcTemplate jdbcTemplate,
            MeterRegistry meterRegistry
    ) {
        return new FundPositionMirror(
                config,
                weightProvider,
                executorApi,
                Clock.systemUTC(),
                jdbcTemplate,
                meterRegistry
        );
    }

    @Bean
    public FundTradeListener fundTradeListener(
            FundConfig config,
            IndexWeightProvider weightProvider,
            FundPositionMirror positionMirror,
            JdbcTemplate jdbcTemplate,
            MeterRegistry meterRegistry
    ) {
        return new FundTradeListener(
                config,
                weightProvider,
                positionMirror,
                jdbcTemplate,
                Clock.systemUTC(),
                meterRegistry
        );
    }

    /**
     * Scheduled task to poll for new trades from PSI index traders.
     *
     * Runs every 1000ms to check for new trades.
     * Note: We create this as a separate bean because @Scheduled annotations
     * are not processed on beans created via new() in @Bean methods.
     */
    @Bean
    @ConditionalOnProperty(prefix = "hft.multi-fund", name = "enabled",
            havingValue = "false", matchIfMissing = true)
    public FundTradePoller fundTradePoller(FundTradeListener tradeListener) {
        return new FundTradePoller(tradeListener);
    }

    @Slf4j
    public static class FundTradePoller {
        private final FundTradeListener tradeListener;

        public FundTradePoller(FundTradeListener tradeListener) {
            this.tradeListener = tradeListener;
            log.info("FundTradePoller initialized - will poll for trades every 1000ms");
        }

        @Scheduled(fixedRate = 1000)
        public void pollForTrades() {
            try {
                tradeListener.pollForTrades();
            } catch (Exception e) {
                log.warn("Error polling for trades: {}", e.getMessage());
            }
        }
    }

    /**
     * Scheduled task to process pending signals.
     *
     * Runs every 100ms to check for signals that have passed their delay period.
     */
    @Bean
    @ConditionalOnProperty(prefix = "hft.multi-fund", name = "enabled",
            havingValue = "false", matchIfMissing = true)
    public FundSignalProcessor fundSignalProcessor(FundPositionMirror positionMirror) {
        return new FundSignalProcessor(positionMirror);
    }

    @Slf4j
    public static class FundSignalProcessor {
        private final FundPositionMirror positionMirror;

        public FundSignalProcessor(FundPositionMirror positionMirror) {
            this.positionMirror = positionMirror;
        }

        @Scheduled(fixedRate = 100)
        public void processPendingSignals() {
            try {
                positionMirror.processPendingSignals();
            } catch (Exception e) {
                log.warn("Error processing pending signals: {}", e.getMessage());
            }
        }
    }
}
