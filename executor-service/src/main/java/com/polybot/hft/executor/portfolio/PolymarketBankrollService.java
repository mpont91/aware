package com.polybot.hft.executor.portfolio;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.polybot.hft.config.HftProperties;
import com.polybot.hft.executor.sim.PaperExchangeSimulator;
import com.polybot.hft.polymarket.api.PolymarketBankrollResponse;
import com.polybot.hft.polymarket.auth.PolymarketAuthContext;
import com.polybot.hft.polymarket.data.PolymarketDataApiClient;
import com.polybot.hft.polymarket.data.PolymarketPosition;
import com.polybot.hft.polymarket.onchain.ContractConfig;
import lombok.NonNull;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.web3j.crypto.Credentials;

import java.math.BigDecimal;
import java.time.Clock;
import java.util.List;

@Service
@RequiredArgsConstructor
public class PolymarketBankrollService {

  private static final TypeReference<List<PolymarketPosition>> POSITIONS_LIST = new TypeReference<>() {
  };

  private final @NonNull HftProperties properties;
  private final @NonNull PolymarketAuthContext authContext;
  private final @NonNull PolymarketDataApiClient dataApiClient;
  private final @NonNull ObjectMapper objectMapper;
  private final @NonNull OnchainErc20BalanceService onchainErc20;
  private final @NonNull PaperExchangeSimulator simulator;
  private final @NonNull Clock clock;
  private final @NonNull PaperBankrollCalculator paperBankroll;

  public PolymarketBankrollResponse snapshot() {
    long now = clock.millis();
    if (simulator.enabled()) {
      // Paper is valued the same way live is, rather than reported as zero.
      // Zeros meant nothing downstream could be exercised until real money was
      // behind it: dynamic sizing had no bankroll to scale against and the
      // circuit breaker had a balance permanently under its floor.
      PaperBankrollCalculator.PaperBook book = paperBankroll.read();
      return new PolymarketBankrollResponse(
          properties.mode().name(),
          null,
          book.cashUsd(),
          book.openValueUsd(),
          BigDecimal.ZERO,
          book.equityUsd(),
          book.openPositions(),
          // Nothing to redeem or merge on paper: settlement is accounted for
          // when the market resolves, not claimed on chain.
          0,
          0,
          now
      );
    }

    String maker = makerAddress();
    if (maker == null || maker.isBlank()) {
      return new PolymarketBankrollResponse(
          properties.mode().name(),
          null,
          BigDecimal.ZERO,
          BigDecimal.ZERO,
          BigDecimal.ZERO,
          BigDecimal.ZERO,
          0,
          0,
          0,
          now
      );
    }

    ContractConfig contracts = ContractConfig.forChainId(properties.polymarket().chainId());
    BigDecimal usdc = onchainErc20.balanceOf(contracts.collateral(), maker, contracts.collateralTokenDecimals());

    JsonNode raw = dataApiClient.getPositions(maker, 500, 0);
    List<PolymarketPosition> positions = objectMapper.convertValue(raw, POSITIONS_LIST);

    BigDecimal cur = BigDecimal.ZERO;
    BigDecimal init = BigDecimal.ZERO;
    int redeemable = 0;
    int mergeable = 0;
    for (PolymarketPosition p : positions) {
      if (p == null) {
        continue;
      }
      if (Boolean.TRUE.equals(p.redeemable())) {
        redeemable++;
      }
      if (Boolean.TRUE.equals(p.mergeable())) {
        mergeable++;
      }
      if (p.currentValue() != null) {
        cur = cur.add(p.currentValue().abs());
      }
      if (p.initialValue() != null) {
        init = init.add(p.initialValue().abs());
      }
    }

    BigDecimal equity = usdc.add(cur);

    return new PolymarketBankrollResponse(
        properties.mode().name(),
        maker,
        usdc,
        cur,
        init,
        equity,
        positions.size(),
        redeemable,
        mergeable,
        now
    );
  }

  private String makerAddress() {
    String funder = authContext.funderAddress().orElse(null);
    if (funder != null && !funder.isBlank()) {
      return funder.toLowerCase();
    }
    return authContext.signerCredentials()
        .map(Credentials::getAddress)
        .map(String::toLowerCase)
        .orElse(null);
  }
}

