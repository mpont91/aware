#!/usr/bin/env python3
"""
AWARE API - Public REST API Service

Provides endpoints for:
- Leaderboard & Trader Profiles
- PSI Indices (PSI-10, PSI-25, PSI-CRYPTO, PSI-POLITICS)
- Hidden Alpha Discovery
- Strategy DNA / Fingerprinting
- Consensus Signal Detection
- Edge Decay Monitoring

Usage:
    python main.py

Environment Variables:
    CLICKHOUSE_HOST - ClickHouse host (default: localhost)
    CLICKHOUSE_PORT - ClickHouse port (default: 8123)
    CLICKHOUSE_DATABASE - Database name (default: polybot)
    API_HOST - API host (default: 0.0.0.0)
    API_PORT - API port (default: 8000)
    LOG_LEVEL - Logging level (default: INFO)
"""

import os
import sys
import logging
from datetime import date, datetime, timezone
from typing import Annotated, Optional

from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, PlainSerializer
import uvicorn

# ─────────────────────────────────────────────────────────────────────────────
# Timestamps
# ─────────────────────────────────────────────────────────────────────────────
# ClickHouse DateTime64 columns here carry no timezone, so the driver hands
# back naive datetimes that are in fact UTC. Serialized as-is they lose that
# fact, and any client parsing ISO-8601 without an offset applies its OWN local
# zone: a trade from a minute ago reads as an hour or two old, off by exactly
# the viewer's UTC offset. Everything leaving this API is stamped UTC instead.


def _as_utc(value):
    """Attach UTC to a naive datetime. Dates and aware values pass through."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def utc_iso(value) -> Optional[str]:
    """ISO-8601 with an explicit offset, or None. Accepts dates and datetimes."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return _as_utc(value).isoformat()
    return str(value)


# Same guarantee for datetime fields declared on response models.
UtcDatetime = Annotated[
    datetime,
    PlainSerializer(lambda d: _as_utc(d).isoformat(), return_type=str, when_used='json'),
]


import clickhouse_connect

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Authentication
from auth import verify_api_key, optional_api_key, is_auth_enabled

# Investment module (Custodial MVP)
# The investor layer (deposits, shares, NAV per share) is gone: this is not a
# fund with outside money, and every figure it produced was an empty valuation.
# Fund pages read /api/fund/summary and /api/fund/pnl instead.

# Add analytics to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'analytics'))

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('aware-api')

# Initialize Rate Limiter
# Default: 100 requests per minute per IP
# Override with RATE_LIMIT env var (e.g., "200/minute")
limiter = Limiter(key_func=get_remote_address)

# Initialize FastAPI
app = FastAPI(
    title="AWARE FUND API",
    description="The Smart Money Index for Prediction Markets",
    version="1.0.0"
)

# Attach rate limiter to app
app.state.limiter = limiter

# ─────────────────────────────────────────────────────────────────────────────
# Error responses
# ─────────────────────────────────────────────────────────────────────────────
# Endpoints throughout this file raise HTTPException(500, detail=str(e)), which
# hands the caller the raw exception: ClickHouse errors naming tables and
# columns, connection errors naming internal hosts and ports. Fine on a private
# deployment, an infrastructure map on a public one. The detail is logged in
# full and replaced with a generic message on the way out.
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code >= 500:
        logger.error(
            "Unhandled error on %s %s: %s", request.method, request.url.path, exc.detail
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": "Internal server error"},
        )
    # 4xx detail is written for the caller and safe to pass through.
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add CORS middleware
# Note: In production, replace "*" with specific allowed origins
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3002",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if os.getenv('ENV', 'development') == 'production' else ["*"],
    allow_credentials=False,  # Don't allow credentials with wildcard origins
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)




# ============================================================================
# MODELS
# ============================================================================

class LeaderboardEntry(BaseModel):
    rank: int
    username: str
    pseudonym: Optional[str]
    proxy_address: str
    smart_money_score: float
    tier: str
    total_pnl: float
    total_volume: float
    win_rate: float
    sharpe_ratio: float
    strategy_type: str
    strategy_confidence: float
    rank_change: int
    total_trades: int = 0
    model_version: Optional[str] = None
    tier_confidence: Optional[float] = None


class TraderProfile(BaseModel):
    username: str
    pseudonym: Optional[str]
    proxy_address: str
    # Scores
    smart_money_score: int
    tier: str
    profitability_score: float
    risk_adjusted_score: float
    consistency_score: float
    track_record_score: float
    # Strategy
    strategy_type: str
    strategy_confidence: float
    complete_set_ratio: float
    direction_bias: float
    # Performance
    total_pnl: float
    total_volume: float
    # Activity
    total_trades: int
    unique_markets: int
    days_active: int
    first_trade_at: Optional[UtcDatetime]
    last_trade_at: Optional[UtcDatetime]


class IndexComposition(BaseModel):
    rank: int
    username: str
    proxy_address: str
    smart_money_score: int
    weight: float
    total_pnl: float


class PSIIndex(BaseModel):
    name: str
    description: str
    trader_count: int
    total_weight: float
    composition: list[IndexComposition]
    calculated_at: UtcDatetime


class HealthResponse(BaseModel):
    status: str
    database: str
    trade_count: int
    trader_count: int
    last_score_update: Optional[UtcDatetime]


class StatsResponse(BaseModel):
    total_trades: int
    total_traders: int
    total_volume_usd: float
    trades_24h: int
    traders_24h: int


class MonitoringResponse(BaseModel):
    """Comprehensive monitoring status"""
    ingestion_status: str  # healthy, degraded, unhealthy
    trades_last_hour: int
    trades_last_24h: int
    traders_last_24h: int
    latest_trade_at: Optional[UtcDatetime]
    ingestion_lag_seconds: int
    markets_active: int
    avg_trades_per_hour: float
    issues: list[str]
    # Pipeline
    total_trades: int
    total_traders: int
    traders_scored: int
    traders_with_pnl: int
    traders_with_sharpe: int
    resolutions_tracked: int
    last_scoring_at: Optional[UtcDatetime]


class DailyStats(BaseModel):
    date: str
    trades: int
    traders: int
    markets: int
    volume_usd: float


class DataFreshness(BaseModel):
    """Data freshness indicators for UI display"""
    status: str  # fresh, stale, outdated
    status_emoji: str  # 🟢, 🟡, 🔴
    latest_trade_at: Optional[UtcDatetime]
    latest_trade_age_seconds: int
    latest_trade_age_human: str  # "2 minutes ago"
    last_scoring_at: Optional[UtcDatetime]
    last_scoring_age_human: str
    last_pnl_at: Optional[UtcDatetime]
    last_pnl_age_human: str
    data_coverage_days: int
    recommendation: str  # For users: "Data is current" or "Scores may be outdated"


# ============================================================================
# DATABASE
# ============================================================================

def get_clickhouse_client():
    """Get ClickHouse client"""
    return clickhouse_connect.get_client(
        host=os.getenv('CLICKHOUSE_HOST', 'localhost'),
        port=int(os.getenv('CLICKHOUSE_PORT', '8123')),
        database=os.getenv('CLICKHOUSE_DATABASE', 'polybot'),
        username=os.getenv('CLICKHOUSE_USER', 'default'),
        password=os.getenv('CLICKHOUSE_PASSWORD', '')
    )


# ============================================================================
# HELPERS
# ============================================================================

def _human_readable_age(seconds: int) -> str:
    """Convert seconds to human readable string like '2 minutes ago'"""
    if seconds < 60:
        return f"{seconds} seconds ago"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    else:
        days = seconds // 86400
        return f"{days} day{'s' if days > 1 else ''} ago"


def _get_freshness_status(lag_seconds: int) -> tuple[str, str]:
    """
    Get freshness status and emoji based on lag.

    Returns (status, emoji) tuple.
    """
    if lag_seconds < 300:  # < 5 minutes
        return 'fresh', '🟢'
    elif lag_seconds < 1800:  # < 30 minutes
        return 'stale', '🟡'
    else:
        return 'outdated', '🔴'


def _sanitize_identifier(value: str, max_length: int = 100) -> str:
    """
    Sanitize a string identifier for safe SQL usage.

    - Escapes single quotes
    - Limits length
    - Removes dangerous characters
    """
    if not value:
        return ''
    # Remove null bytes and control characters
    sanitized = ''.join(c for c in value if c.isprintable() and c not in '\x00\n\r')
    # Escape single quotes for SQL
    sanitized = sanitized.replace("'", "''")
    # Limit length
    return sanitized[:max_length]


def _validate_wallet_address(address: str) -> bool:
    """Validate Ethereum-style wallet address format."""
    import re
    return bool(re.match(r'^0x[a-fA-F0-9]{40}$', address))


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    try:
        client = get_clickhouse_client()

        # Get counts
        trade_count = client.query(
            "SELECT count() FROM aware_global_trades_dedup"
        ).result_rows[0][0]

        trader_count = client.query(
            "SELECT count() FROM aware_smart_money_scores FINAL"
        ).result_rows[0][0]

        # Get last update
        result = client.query(
            "SELECT max(calculated_at) FROM aware_smart_money_scores"
        )
        last_update = result.result_rows[0][0] if result.result_rows else None

        return HealthResponse(
            status="healthy",
            database="connected",
            trade_count=trade_count,
            trader_count=trader_count,
            last_score_update=last_update
        )

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            database=str(e),
            trade_count=0,
            trader_count=0,
            last_score_update=None
        )


@app.get("/api/freshness", response_model=DataFreshness)
async def get_data_freshness():
    """
    Get data freshness indicators for UI display.

    Returns human-readable timestamps and status indicators
    to help users understand how current the data is.
    """
    try:
        client = get_clickhouse_client()
        from datetime import timezone

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        # Get latest trade timestamp
        result = client.query("SELECT max(ts) FROM aware_global_trades_dedup")
        latest_trade = result.result_rows[0][0] if result.result_rows else None

        trade_lag_seconds = 0
        if latest_trade:
            trade_lag_seconds = int((now_utc - latest_trade).total_seconds())

        # Get last scoring timestamp
        result = client.query("SELECT max(calculated_at) FROM aware_smart_money_scores")
        last_scoring = result.result_rows[0][0] if result.result_rows else None

        scoring_lag_seconds = 0
        if last_scoring:
            scoring_lag_seconds = int((now_utc - last_scoring).total_seconds())

        # Get last P&L calculation timestamp
        result = client.query("SELECT max(calculated_at) FROM aware_trader_pnl")
        last_pnl = result.result_rows[0][0] if result.result_rows else None

        pnl_lag_seconds = 0
        if last_pnl:
            pnl_lag_seconds = int((now_utc - last_pnl).total_seconds())

        # Get data coverage (days of data)
        result = client.query("""
            SELECT dateDiff('day', min(ts), max(ts)) + 1
            FROM aware_global_trades_dedup
        """)
        data_coverage_days = result.result_rows[0][0] if result.result_rows else 0

        # Determine overall status (based on trade ingestion lag)
        status, status_emoji = _get_freshness_status(trade_lag_seconds)

        # Generate recommendation
        if status == 'fresh':
            recommendation = "Data is current and reliable"
        elif status == 'stale':
            recommendation = "Data may be slightly delayed - scores are still valid"
        else:
            recommendation = "Data is outdated - please wait for ingestion to resume"

        return DataFreshness(
            status=status,
            status_emoji=status_emoji,
            latest_trade_at=latest_trade,
            latest_trade_age_seconds=trade_lag_seconds,
            latest_trade_age_human=_human_readable_age(trade_lag_seconds) if latest_trade else "No data",
            last_scoring_at=last_scoring,
            last_scoring_age_human=_human_readable_age(scoring_lag_seconds) if last_scoring else "Never",
            last_pnl_at=last_pnl,
            last_pnl_age_human=_human_readable_age(pnl_lag_seconds) if last_pnl else "Never",
            data_coverage_days=data_coverage_days or 0,
            recommendation=recommendation
        )

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Freshness check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/monitoring", response_model=MonitoringResponse)
async def get_monitoring():
    """
    Comprehensive monitoring endpoint for data quality and pipeline health.

    Returns ingestion status, lag metrics, and pipeline health.
    """
    try:
        client = get_clickhouse_client()

        # Ingestion metrics
        result = client.query("""
            SELECT
                countIf(ts >= now() - INTERVAL 1 HOUR) AS trades_1h,
                countIf(ts >= now() - INTERVAL 24 HOUR) AS trades_24h,
                uniqExactIf(proxy_address, ts >= now() - INTERVAL 24 HOUR) AS traders_24h,
                uniqExactIf(market_slug, ts >= now() - INTERVAL 24 HOUR) AS markets_active,
                max(ts) AS latest_trade
            FROM aware_global_trades_dedup
        """)
        row = result.result_rows[0]
        trades_1h = row[0]
        trades_24h = row[1]
        traders_24h = row[2]
        markets_active = row[3]
        latest_trade = row[4]

        # Calculate lag
        lag_seconds = 0
        if latest_trade:
            from datetime import timezone
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            lag_seconds = int((now_utc - latest_trade).total_seconds())

        avg_per_hour = trades_24h / 24.0 if trades_24h > 0 else 0

        # Determine status
        status = 'healthy'
        issues = []

        if lag_seconds > 300:
            issues.append(f"Ingestion lag: {lag_seconds}s (>5min)")
            status = 'degraded'
        if lag_seconds > 900:
            status = 'unhealthy'
        if trades_1h == 0:
            issues.append("No trades in last hour")
            status = 'unhealthy'

        # Pipeline metrics (with fallbacks for missing tables)
        def safe_count(query: str) -> int:
            try:
                return client.query(query).result_rows[0][0]
            except Exception:
                return 0

        def safe_datetime(query: str):
            try:
                result = client.query(query)
                return result.result_rows[0][0] if result.result_rows else None
            except Exception:
                return None

        total_trades = safe_count("SELECT count() FROM aware_global_trades_dedup")
        total_traders = safe_count("SELECT uniqExact(proxy_address) FROM aware_global_trades_dedup")
        traders_scored = safe_count("SELECT count() FROM aware_smart_money_scores FINAL")
        traders_pnl = safe_count("SELECT count() FROM aware_trader_pnl FINAL WHERE total_realized_pnl != 0")
        traders_sharpe = safe_count("SELECT count() FROM aware_ml_scores FINAL WHERE sharpe_ratio != 0")
        resolutions = safe_count("SELECT count() FROM aware_resolutions FINAL")
        last_scoring = safe_datetime("SELECT max(calculated_at) FROM aware_smart_money_scores")

        return MonitoringResponse(
            ingestion_status=status,
            trades_last_hour=trades_1h,
            trades_last_24h=trades_24h,
            traders_last_24h=traders_24h,
            latest_trade_at=latest_trade,
            ingestion_lag_seconds=lag_seconds,
            markets_active=markets_active,
            avg_trades_per_hour=round(avg_per_hour, 1),
            issues=issues,
            total_trades=total_trades,
            total_traders=total_traders,
            traders_scored=traders_scored,
            traders_with_pnl=traders_pnl,
            traders_with_sharpe=traders_sharpe,
            resolutions_tracked=resolutions,
            last_scoring_at=last_scoring
        )

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Monitoring check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/monitoring/daily", response_model=list[DailyStats])
async def get_daily_stats(days: int = Query(default=7, ge=1, le=30)):
    """Get daily trade statistics for the last N days"""
    try:
        client = get_clickhouse_client()

        result = client.query(f"""
            SELECT
                toDate(ts) AS trade_date,
                count() AS trades,
                uniqExact(proxy_address) AS traders,
                uniqExact(market_slug) AS markets,
                sum(notional) AS volume_usd
            FROM aware_global_trades_dedup
            WHERE ts >= now() - INTERVAL {days} DAY
            GROUP BY trade_date
            ORDER BY trade_date DESC
        """)

        stats = []
        for row in result.result_rows:
            stats.append(DailyStats(
                date=utc_iso(row[0]) if row[0] else '',
                trades=row[1],
                traders=row[2],
                markets=row[3],
                volume_usd=round(row[4], 2)
            ))

        return stats

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Daily stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """Get overall statistics"""
    try:
        client = get_clickhouse_client()

        result = client.query("""
            SELECT
                count() AS total_trades,
                uniqExact(proxy_address) AS total_traders,
                sum(notional) AS total_volume,
                countIf(ts >= now() - INTERVAL 1 DAY) AS trades_24h,
                uniqExactIf(proxy_address, ts >= now() - INTERVAL 1 DAY) AS traders_24h
            FROM aware_global_trades_dedup
        """)

        row = result.result_rows[0]
        return StatsResponse(
            total_trades=row[0],
            total_traders=row[1],
            total_volume_usd=row[2],
            trades_24h=row[3],
            traders_24h=row[4]
        )

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Valid tier and strategy values (whitelist for SQL injection prevention)
VALID_TIERS = {'BRONZE', 'SILVER', 'GOLD', 'DIAMOND'}
VALID_STRATEGIES = {'UNKNOWN', 'ARBITRAGEUR', 'MARKET_MAKER', 'DIRECTIONAL_FUNDAMENTAL',
                    'DIRECTIONAL_MOMENTUM', 'EVENT_DRIVEN', 'SCALPER', 'HYBRID'}


@app.get("/api/leaderboard", response_model=list[LeaderboardEntry])
@limiter.limit("100/minute")
async def get_leaderboard(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    tier: Optional[str] = Query(default=None),
    strategy: Optional[str] = Query(default=None),
    api_key: Optional[str] = Depends(optional_api_key)
):
    """
    Get the AWARE leaderboard.

    Traders ranked by Smart Money Score.
    """
    try:
        client = get_clickhouse_client()

        # Input validation - whitelist approach prevents SQL injection
        where_clauses = []
        if tier:
            tier_upper = tier.upper()
            if tier_upper not in VALID_TIERS:
                raise HTTPException(status_code=400, detail=f"Invalid tier. Must be one of: {', '.join(VALID_TIERS)}")
            where_clauses.append(f"tier = '{tier_upper}'")
        if strategy:
            strategy_upper = strategy.upper()
            if strategy_upper not in VALID_STRATEGIES:
                raise HTTPException(status_code=400, detail=f"Invalid strategy. Must be one of: {', '.join(VALID_STRATEGIES)}")
            where_clauses.append(f"strategy_type = '{strategy_upper}'")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # Use the ML-enhanced leaderboard view which includes sharpe_ratio and win_rate
        query = f"""
            SELECT
                rank,
                username,
                pseudonym,
                proxy_address,
                smart_money_score,
                tier,
                total_pnl,
                total_volume,
                coalesce(win_rate, 0.0) AS win_rate,
                coalesce(sharpe_ratio, 0.0) AS sharpe_ratio,
                strategy_type,
                strategy_confidence,
                0 AS rank_change,
                coalesce(p.total_trades, 0) AS total_trades,
                lb.model_version,
                lb.tier_confidence
            FROM aware_leaderboard_ml AS lb
            LEFT JOIN (SELECT proxy_address, total_trades FROM aware_trader_profiles FINAL) AS p
                ON lb.proxy_address = p.proxy_address
            WHERE {where_sql}
            ORDER BY rank ASC
            LIMIT {limit} OFFSET {offset}
        """

        result = client.query(query)

        entries = []
        for row in result.result_rows:
            entries.append(LeaderboardEntry(
                rank=row[0],
                username=row[1] or '',
                pseudonym=row[2],
                proxy_address=row[3],
                smart_money_score=row[4] or 0,
                tier=row[5] or 'BRONZE',
                total_pnl=row[6] or 0,
                total_volume=row[7] or 0,
                win_rate=row[8] or 0,
                sharpe_ratio=row[9] or 0,
                strategy_type=row[10] or 'UNKNOWN',
                strategy_confidence=row[11] or 0,
                rank_change=row[12] or 0,
                total_trades=row[13] or 0,
                model_version=row[14] if len(row) > 14 else None,
                tier_confidence=row[15] if len(row) > 15 else None
            ))

        return entries

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get leaderboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/traders/{identifier}", response_model=TraderProfile)
async def get_trader(identifier: str):
    """
    Get detailed profile for a trader.

    Looks up by username or proxy_address (wallet address).
    """
    try:
        client = get_clickhouse_client()

        # Check if identifier looks like a wallet address (starts with 0x)
        is_address = identifier.lower().startswith('0x')

        query = """
            SELECT
                s.username,
                p.pseudonym,
                s.proxy_address,
                s.total_score,
                s.tier,
                s.profitability_score,
                s.risk_adjusted_score,
                s.consistency_score,
                s.track_record_score,
                s.strategy_type,
                s.strategy_confidence,
                p.complete_set_ratio,
                p.direction_bias,
                p.total_pnl,
                p.total_volume_usd,
                p.total_trades,
                p.unique_markets,
                p.days_active,
                p.first_trade_at,
                p.last_trade_at
            FROM (SELECT * FROM aware_smart_money_scores FINAL) AS s
            LEFT JOIN (SELECT * FROM aware_trader_profiles FINAL) AS p
                ON s.proxy_address = p.proxy_address
            WHERE lower(s.username) = lower(%(identifier)s)
               OR lower(p.username) = lower(%(identifier)s)
               OR lower(s.proxy_address) = lower(%(identifier)s)
               OR lower(p.proxy_address) = lower(%(identifier)s)
            LIMIT 1
        """

        result = client.query(query, parameters={'identifier': identifier})

        if not result.result_rows:
            raise HTTPException(status_code=404, detail=f"Trader '{identifier}' not found")

        row = result.result_rows[0]
        return TraderProfile(
            username=row[0] or '',
            pseudonym=row[1],
            proxy_address=row[2],
            smart_money_score=row[3],
            tier=row[4],
            profitability_score=row[5],
            risk_adjusted_score=row[6],
            consistency_score=row[7],
            track_record_score=row[8],
            strategy_type=row[9],
            strategy_confidence=row[10],
            complete_set_ratio=row[11] or 0,
            direction_bias=row[12] or 0.5,
            total_pnl=row[13] or 0,
            total_volume=row[14] or 0,
            total_trades=row[15] or 0,
            unique_markets=row[16] or 0,
            days_active=row[17] or 0,
            first_trade_at=row[18],
            last_trade_at=row[19]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get trader: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# How stale a mark may be before a position is shown unpriced. Polymarket
# markets trade continuously, so a token with no print in this window has no
# price anyone is currently willing to pay; inventing one inflates the P&L.
TRADER_MARK_MAX_AGE_HOURS = 6


@app.get("/api/traders/{address}/activity")
async def get_trader_activity(
    address: str,
    days: int = Query(default=180, ge=7, le=730),
    trade_limit: int = Query(default=25, ge=1, le=200),
):
    """
    Everything the trader detail page plots: the realized P&L curve, the
    category split, the positions still open, and the latest trades.

    All four come from observed Polymarket activity for this wallet. Open
    positions are marked to the last print on the token, and left unpriced
    when that print is older than TRADER_MARK_MAX_AGE_HOURS.
    """
    try:
        client = get_clickhouse_client()
        params = {'addr': address.lower(), 'days': days, 'lim': trade_limit}

        # ── Realized P&L curve ──────────────────────────────────────────────
        # One point per day a market this trader held actually resolved.
        # Unresolved positions are deliberately absent: they are estimates,
        # and the curve is the settled record.
        curve_rows = client.query("""
            SELECT toDate(resolved_at) AS d, sum(realized_pnl) AS daily
            FROM (SELECT * FROM aware_position_pnl FINAL)
            WHERE lower(proxy_address) = %(addr)s
              AND resolved_at > toDateTime64('1971-01-01 00:00:00', 3)
              AND resolved_at >= now() - INTERVAL %(days)s DAY
            GROUP BY d
            ORDER BY d
        """, parameters=params).result_rows

        pnl_curve = []
        running = 0.0
        for d, daily in curve_rows:
            running += float(daily or 0)
            pnl_curve.append({
                'date': utc_iso(d),
                'realized_pnl': round(float(daily or 0), 2),
                'cumulative_pnl': round(running, 2),
            })

        # ── Category split ──────────────────────────────────────────────────
        # Volume and trade count come from every trade; the win rate can only
        # come from positions that resolved, so the two are queried apart and
        # merged. A category with no resolved position yet has win_rate None
        # rather than a zero that would read as "never wins".
        cat_rows = client.query("""
            SELECT
                if(c.market_category = '', 'UNCLASSIFIED', c.market_category) AS category,
                sum(t.notional) AS volume,
                count() AS trade_count
            FROM aware_global_trades_dedup t
            LEFT JOIN (SELECT * FROM aware_market_classifications FINAL) c
                ON t.market_slug = c.market_slug
            WHERE lower(t.proxy_address) = %(addr)s
            GROUP BY category
            ORDER BY volume DESC
        """, parameters=params).result_rows

        win_rows = client.query("""
            SELECT
                if(c.market_category = '', 'UNCLASSIFIED', c.market_category) AS category,
                countIf(p.realized_pnl > 0) AS wins,
                count() AS settled
            FROM (SELECT * FROM aware_position_pnl FINAL) p
            LEFT JOIN (SELECT * FROM aware_market_classifications FINAL) c
                ON p.market_slug = c.market_slug
            WHERE lower(p.proxy_address) = %(addr)s
              AND p.resolved_at > toDateTime64('1971-01-01 00:00:00', 3)
            GROUP BY category
        """, parameters=params).result_rows
        win_by_cat = {r[0]: (int(r[1]), int(r[2])) for r in win_rows}

        total_volume = sum(float(r[1] or 0) for r in cat_rows) or 1.0
        categories = []
        for category, volume, trade_count in cat_rows:
            wins, settled = win_by_cat.get(category, (0, 0))
            categories.append({
                'category': category,
                'volume': round(float(volume or 0), 2),
                'trade_count': int(trade_count),
                'share_pct': round(100 * float(volume or 0) / total_volume, 1),
                'win_rate': round(100 * wins / settled, 1) if settled else None,
                'settled_positions': settled,
            })

        # ── Open positions ──────────────────────────────────────────────────
        # Net long exposure on markets with no resolution recorded. Netting
        # buys against sells is what makes this "open" rather than "traded":
        # a round trip cancels out and correctly disappears.
        pos_rows = client.query("""
            SELECT
                t.condition_id AS condition_id,
                t.token_id AS token_id,
                t.market_slug AS market_slug,
                any(t.title) AS title,
                t.outcome AS outcome,
                sumIf(t.size, t.side = 'BUY') - sumIf(t.size, t.side = 'SELL') AS net_shares,
                sumIf(t.notional, t.side = 'BUY') - sumIf(t.notional, t.side = 'SELL') AS net_cost
            FROM aware_global_trades_dedup t
            WHERE lower(t.proxy_address) = %(addr)s
              AND t.condition_id NOT IN (
                  SELECT condition_id
                  FROM (SELECT * FROM aware_market_resolutions FINAL)
                  WHERE is_resolved = 1
              )
            GROUP BY condition_id, token_id, market_slug, outcome
            HAVING net_shares > 0.01
            ORDER BY net_cost DESC
            LIMIT 100
        """, parameters=params).result_rows

        marks = {}
        if pos_rows:
            mark_rows = client.query("""
                SELECT token_id, argMax(price, ts) AS last_price, max(ts) AS last_ts
                FROM aware_global_trades
                WHERE token_id IN %(tokens)s
                  AND ts >= now() - INTERVAL %(hours)s HOUR
                GROUP BY token_id
            """, parameters={
                'tokens': tuple({r[1] for r in pos_rows}),
                'hours': TRADER_MARK_MAX_AGE_HOURS,
            }).result_rows
            marks = {r[0]: (float(r[1]), r[2]) for r in mark_rows}

        open_positions = []
        for condition_id, token_id, market_slug, title, outcome, net_shares, net_cost in pos_rows:
            shares = float(net_shares)
            cost = float(net_cost)
            mark = marks.get(token_id)
            entry = cost / shares if shares else 0.0
            open_positions.append({
                'condition_id': condition_id,
                'market_slug': market_slug,
                'title': title or market_slug,
                'outcome': outcome,
                'shares': round(shares, 2),
                'cost': round(cost, 2),
                'avg_entry_price': round(entry, 4),
                'current_price': round(mark[0], 4) if mark else None,
                'unrealized_pnl': round(mark[0] * shares - cost, 2) if mark else None,
                'priced_at': utc_iso(mark[1]) if mark else None,
            })

        # ── Recent trades ───────────────────────────────────────────────────
        trade_rows = client.query("""
            SELECT ts, market_slug, title, outcome, side, price, size, notional
            FROM aware_global_trades_dedup
            WHERE lower(proxy_address) = %(addr)s
            ORDER BY ts DESC
            LIMIT %(lim)s
        """, parameters=params).result_rows

        recent_trades = [{
            'ts': utc_iso(r[0]),
            'market_slug': r[1],
            'title': r[2] or r[1],
            'outcome': r[3],
            'side': r[4],
            'price': round(float(r[5]), 4),
            'size': round(float(r[6]), 2),
            'notional': round(float(r[7]), 2),
        } for r in trade_rows]

        return {
            'proxy_address': address,
            'mark_max_age_hours': TRADER_MARK_MAX_AGE_HOURS,
            'pnl_curve': pnl_curve,
            'categories': categories,
            'open_positions': open_positions,
            'recent_trades': recent_trades,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get trader activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/index/psi-10", response_model=PSIIndex)
async def get_psi_10():
    """
    Get the PSI-10 index composition.

    Top 10 traders weighted by Smart Money Score.
    """
    try:
        client = get_clickhouse_client()

        # Get top 10 by score
        query = """
            SELECT
                s.rank,
                s.username,
                s.proxy_address,
                s.total_score,
                p.total_pnl
            FROM (SELECT * FROM aware_smart_money_scores FINAL) AS s
            LEFT JOIN (SELECT * FROM aware_trader_profiles FINAL) AS p
                ON s.proxy_address = p.proxy_address
            ORDER BY s.rank ASC
            LIMIT 10
        """

        result = client.query(query)

        # Calculate weights (proportional to score)
        total_score = sum(row[3] for row in result.result_rows)

        composition = []
        for row in result.result_rows:
            weight = row[3] / total_score if total_score > 0 else 0
            composition.append(IndexComposition(
                rank=row[0],
                username=row[1] or '',
                proxy_address=row[2],
                smart_money_score=row[3],
                weight=weight,
                total_pnl=row[4] or 0
            ))

        # Get last calculation time
        calc_result = client.query(
            "SELECT max(calculated_at) FROM aware_smart_money_scores"
        )
        calculated_at = calc_result.result_rows[0][0] if calc_result.result_rows else datetime.utcnow()

        return PSIIndex(
            name="PSI-10",
            description="Top 10 traders weighted by Smart Money Score",
            trader_count=len(composition),
            total_weight=1.0,
            composition=composition,
            calculated_at=calculated_at
        )

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get PSI-10: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/indices/{index_type}", response_model=PSIIndex)
async def get_index_by_type(index_type: str):
    """
    Get any PSI index by type.

    Supported index types: PSI-10, PSI-25, PSI-50, PSI-CRYPTO, PSI-POLITICS, PSI-SPORTS
    """
    try:
        client = get_clickhouse_client()
        index_upper = index_type.upper()

        # Get index from aware_psi_index table
        # Table columns: index_type, username, proxy_address, weight, total_score,
        #                sharpe_ratio, strategy_type, created_at, rebalanced_at
        query = """
            SELECT
                proxy_address,
                username,
                weight,
                total_score,
                rebalanced_at
            FROM polybot.aware_psi_index FINAL
            WHERE index_type = %(index_type)s
            ORDER BY weight DESC
        """

        result = client.query(query, parameters={'index_type': index_upper})

        if not result.result_rows:
            raise HTTPException(status_code=404, detail=f"Index '{index_type}' not found")

        composition = []
        for i, row in enumerate(result.result_rows):
            composition.append(IndexComposition(
                rank=i + 1,
                username=row[1] or '',
                proxy_address=row[0],
                smart_money_score=row[3] or 0,  # total_score
                weight=float(row[2]) if row[2] else 0,
                total_pnl=0  # Not stored in index table
            ))

        # Get last calculation time
        calc_result = client.query(
            "SELECT max(rebalanced_at) FROM polybot.aware_psi_index WHERE index_type = %(index_type)s",
            parameters={'index_type': index_upper}
        )
        calculated_at = calc_result.result_rows[0][0] if calc_result.result_rows else datetime.utcnow()

        return PSIIndex(
            name=index_upper,
            description=f"PSI {index_upper} index composition",
            trader_count=len(composition),
            total_weight=sum(c.weight for c in composition),
            composition=composition,
            calculated_at=calculated_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get index {index_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# HIDDEN ALPHA ENDPOINTS
# ============================================================================

@app.get("/api/discovery/hidden-gems")
async def get_hidden_gems(limit: int = Query(default=10, ge=1, le=50)):
    """
    Find Hidden Gems: High quality traders with low visibility.

    These are traders with good scores but low volume - not yet on the public radar.
    """
    try:
        client = get_clickhouse_client()

        # Join scores with profiles to get all metrics
        query = f"""
        SELECT
            s.username,
            s.total_score,
            s.profitability_score,
            s.risk_adjusted_score,
            p.total_volume_usd,
            p.total_trades,
            p.days_active,
            p.total_pnl,
            s.strategy_type
        FROM (SELECT * FROM polybot.aware_smart_money_scores FINAL) AS s
        JOIN (SELECT * FROM polybot.aware_trader_profiles FINAL) AS p
            ON s.proxy_address = p.proxy_address
        WHERE
            s.total_score >= 40
            AND p.total_volume_usd <= 50000
            AND p.total_trades >= 20
            AND s.username != ''
        ORDER BY s.risk_adjusted_score DESC
        LIMIT {limit}
        """

        result = client.query(query)

        discoveries = []
        for row in result.result_rows:
            volume = row[4] or 0
            score = row[1] or 0
            risk_score = row[3] or 0
            visibility = min(100, (volume / 100000) * 100)
            discovery_score = min(100, score + (50 - visibility / 2))

            discoveries.append({
                'username': row[0],
                'discovery_type': 'HIDDEN_GEM',
                'discovery_score': round(discovery_score / 100, 2),
                'visibility_score': round(visibility, 1),
                'smart_money_score': score,
                'sharpe_ratio': round(risk_score / 30, 2),  # Approximate from risk score
                'win_rate': round(row[2] or 0, 1),  # Use profitability as proxy
                'volume_usd': round(volume, 0),
                'total_trades': row[5],
                'total_pnl': round(row[7] or 0, 2),
                'reason': f"Score {score} with only ${volume:,.0f} volume"
            })

        return {
            'discovery_type': 'HIDDEN_GEM',
            'count': len(discoveries),
            'discoveries': discoveries
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to find hidden gems: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/discovery/rising-stars")
async def get_rising_stars(
    max_days: int = Query(default=30, ge=1, le=90),
    limit: int = Query(default=10, ge=1, le=50)
):
    """
    Find Rising Stars: New traders with exceptional early performance.

    These traders have been active for less than 30 days but show
    exceptional metrics - potential future top performers.
    """
    try:
        client = get_clickhouse_client()

        query = f"""
        SELECT
            s.username,
            s.total_score,
            s.profitability_score,
            s.risk_adjusted_score,
            p.total_volume_usd,
            p.total_trades,
            p.days_active,
            p.total_pnl,
            s.strategy_type
        FROM (SELECT * FROM polybot.aware_smart_money_scores FINAL) AS s
        JOIN (SELECT * FROM polybot.aware_trader_profiles FINAL) AS p
            ON s.proxy_address = p.proxy_address
        WHERE
            p.days_active <= {max_days}
            AND s.profitability_score >= 10
            AND p.total_trades >= 10
            AND s.username != ''
        ORDER BY s.total_score DESC
        LIMIT {limit}
        """

        result = client.query(query)

        discoveries = []
        for row in result.result_rows:
            days_active = row[6] or 0
            score = row[1] or 0
            profit_score = row[2] or 0
            risk_score = row[3] or 0

            newness_score = max(0, 30 - days_active)
            discovery_score = min(100, newness_score + score)

            discoveries.append({
                'username': row[0],
                'discovery_type': 'RISING_STAR',
                'discovery_score': round(discovery_score / 100, 2),
                'days_active': days_active,
                'smart_money_score': score,
                'sharpe_ratio': round(risk_score / 30, 2),
                'win_rate': round(profit_score, 1),
                'total_trades': row[5],
                'total_pnl': round(row[7] or 0, 2),
                'reason': f"Only {days_active} days active with score {score}"
            })

        return {
            'discovery_type': 'RISING_STAR',
            'count': len(discoveries),
            'discoveries': discoveries
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to find rising stars: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/discovery/niche-specialists")
async def get_niche_specialists(limit: int = Query(default=10, ge=1, le=50)):
    """
    Find Niche Specialists: Traders who dominate specific market categories.

    These traders focus on one area and significantly outperform in that category.
    """
    try:
        client = get_clickhouse_client()

        query = f"""
        SELECT
            s.username,
            s.total_score,
            s.profitability_score,
            s.risk_adjusted_score,
            p.total_volume_usd,
            p.unique_markets,
            p.total_trades,
            s.strategy_type,
            p.total_pnl
        FROM (SELECT * FROM polybot.aware_smart_money_scores FINAL) AS s
        JOIN (SELECT * FROM polybot.aware_trader_profiles FINAL) AS p
            ON s.proxy_address = p.proxy_address
        WHERE
            p.unique_markets <= 5
            AND p.total_trades >= 20
            AND s.total_score >= 35
            AND s.username != ''
        ORDER BY s.risk_adjusted_score DESC
        LIMIT {limit}
        """

        result = client.query(query)

        discoveries = []
        for row in result.result_rows:
            unique_markets = row[5] or 1
            score = row[1] or 0
            risk_score = row[3] or 0
            concentration = 1.0 / max(1, unique_markets)
            discovery_score = min(100, score + concentration * 30)

            discoveries.append({
                'username': row[0],
                'discovery_type': 'NICHE_SPECIALIST',
                'discovery_score': round(discovery_score / 100, 2),
                'unique_markets': unique_markets,
                'market_concentration': round(concentration * 100, 1),
                'smart_money_score': score,
                'sharpe_ratio': round(risk_score / 30, 2),
                'win_rate': round(row[2] or 0, 1),
                'total_trades': row[6],
                'total_pnl': round(row[8] or 0, 2),
                'reason': f"Focused on {unique_markets} markets with score {score}"
            })

        return {
            'discovery_type': 'NICHE_SPECIALIST',
            'count': len(discoveries),
            'discoveries': discoveries
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to find niche specialists: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CONSENSUS SIGNAL ENDPOINTS
# ============================================================================

@app.get("/api/consensus/markets")
async def get_consensus_markets(
    min_traders: int = Query(default=3, ge=2, le=20),
    min_volume: float = Query(default=5000, ge=0),
    hours: int = Query(default=48, ge=1, le=168)
):
    """
    Get markets where smart money is forming consensus.

    Returns markets where multiple top traders are taking similar positions.
    """
    try:
        client = get_clickhouse_client()

        # Keyed on proxy_address, not username: most Polymarket wallets have no
        # username set, so joining on it silently matched nothing but the empty
        # string and the endpoint returned no signals at all.
        query = f"""
        WITH smart_traders AS (
            SELECT proxy_address, total_score
            FROM polybot.aware_smart_money_scores FINAL
            WHERE total_score >= 45
              AND proxy_address != ''
            LIMIT 100
        )
        SELECT
            t.market_slug,
            any(t.title) as title,
            t.outcome,
            count(DISTINCT t.proxy_address) as trader_count,
            sum(t.notional) as total_volume,
            avg(t.price) as avg_price,
            avg(st.total_score) as avg_score
        FROM polybot.aware_global_trades t
        INNER JOIN smart_traders st ON t.proxy_address = st.proxy_address
        WHERE t.ts >= now() - INTERVAL {hours} HOUR
        GROUP BY t.market_slug, t.outcome
        HAVING count(DISTINCT t.proxy_address) >= {min_traders}
           AND sum(t.notional) >= {min_volume}
        ORDER BY total_volume DESC
        LIMIT 20
        """

        result = client.query(query)

        signals = []
        for row in result.result_rows:
            signals.append({
                'market_slug': row[0],
                'title': row[1],
                'favored_outcome': row[2],
                'trader_count': row[3],
                'total_volume': round(row[4], 2),
                'avg_price': round(row[5], 3),
                'avg_score': round(row[6], 1),
                'consensus_strength': 'STRONG' if row[3] >= 5 else 'MODERATE' if row[3] >= 3 else 'WEAK'
            })

        return {
            'lookback_hours': hours,
            'min_traders': min_traders,
            'signal_count': len(signals),
            'signals': signals
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get consensus: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/consensus/market/{market_slug}")
async def get_market_consensus(market_slug: str, hours: int = Query(default=48, ge=1, le=168)):
    """
    Get detailed smart money analysis for a specific market.
    """
    try:
        client = get_clickhouse_client()

        # Sanitize market_slug to prevent SQL injection
        safe_market_slug = _sanitize_identifier(market_slug, max_length=200)
        if not safe_market_slug:
            raise HTTPException(status_code=400, detail="Invalid market slug")

        query = f"""
        WITH smart_traders AS (
            SELECT username, total_score as smart_money_score
            FROM polybot.aware_smart_money_scores FINAL
            WHERE total_score >= 45
        )
        SELECT
            t.username,
            s.smart_money_score,
            t.side,
            t.outcome,
            sum(t.notional) as total_notional,
            count() as trade_count,
            max(t.ts) as last_trade
        FROM polybot.aware_global_trades t
        JOIN smart_traders s ON t.username = s.username
        WHERE
            t.market_slug = '{safe_market_slug}'
            AND t.ts >= now() - INTERVAL {hours} HOUR
        GROUP BY t.username, s.smart_money_score, t.side, t.outcome
        ORDER BY total_notional DESC
        """

        result = client.query(query)

        traders = []
        yes_volume = 0
        no_volume = 0

        for row in result.result_rows:
            outcome = (row[3] or '').upper()
            side = (row[2] or '').upper()
            notional = row[4]

            # Determine direction
            if (side == 'BUY' and 'YES' in outcome) or (side == 'SELL' and 'NO' in outcome):
                direction = 'YES'
                yes_volume += notional
            else:
                direction = 'NO'
                no_volume += notional

            traders.append({
                'username': row[0],
                'smart_money_score': row[1],
                'direction': direction,
                'volume': round(notional, 2),
                'trade_count': row[5],
                'last_trade': utc_iso(row[6]) if row[6] else None
            })

        total_volume = yes_volume + no_volume

        return {
            'market_slug': market_slug,
            'lookback_hours': hours,
            'summary': {
                'total_smart_money_volume': round(total_volume, 2),
                'yes_volume': round(yes_volume, 2),
                'no_volume': round(no_volume, 2),
                'consensus_direction': 'YES' if yes_volume > no_volume else 'NO' if no_volume > yes_volume else 'SPLIT',
                'consensus_strength': round(max(yes_volume, no_volume) / total_volume * 100, 1) if total_volume > 0 else 0
            },
            'traders': traders
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get market consensus: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# EDGE DECAY ENDPOINTS
# ============================================================================

@app.get("/api/edge/health/{username}")
async def get_trader_health(username: str):
    """
    Get edge health check for a trader.

    Compares recent vs historical performance to detect edge decay.
    """
    try:
        client = get_clickhouse_client()

        # Sanitize username to prevent SQL injection
        safe_username = _sanitize_identifier(username)
        if not safe_username:
            raise HTTPException(status_code=400, detail="Invalid username")

        # Get historical metrics (90 days)
        hist_query = f"""
        SELECT
            count() as trade_count,
            avg(notional) as avg_return,
            stddevPop(notional) as return_std,
            sum(notional) as total_pnl
        FROM polybot.aware_global_trades
        WHERE
            username = '{safe_username}'
            AND ts >= now() - INTERVAL 90 DAY
        """

        # Get recent metrics (30 days)
        recent_query = f"""
        SELECT
            count() as trade_count,
            avg(notional) as avg_return,
            stddevPop(notional) as return_std,
            sum(notional) as total_pnl
        FROM polybot.aware_global_trades
        WHERE
            username = '{safe_username}'
            AND ts >= now() - INTERVAL 30 DAY
        """

        hist_result = client.query(hist_query)
        recent_result = client.query(recent_query)

        if not hist_result.result_rows or hist_result.result_rows[0][0] < 20:
            return {
                'username': username,
                'status': 'INSUFFICIENT_DATA',
                'message': 'Not enough trading history for analysis'
            }

        hist = hist_result.result_rows[0]
        recent = recent_result.result_rows[0]

        hist_return = hist[1] or 0
        hist_std = hist[2] or 1
        hist_sharpe = hist_return / hist_std if hist_std > 0 else 0

        recent_return = recent[1] or 0
        recent_std = recent[2] or 1
        recent_sharpe = recent_return / recent_std if recent_std > 0 else 0

        # Calculate decay
        if hist_sharpe > 0:
            sharpe_change = (recent_sharpe - hist_sharpe) / hist_sharpe
        else:
            sharpe_change = 0

        # Determine status
        if sharpe_change < -0.40:
            status = 'CRITICAL'
            health_score = max(0, 100 + sharpe_change * 100)
        elif sharpe_change < -0.25:
            status = 'SEVERE'
            health_score = max(20, 100 + sharpe_change * 100)
        elif sharpe_change < -0.15:
            status = 'MODERATE'
            health_score = max(40, 100 + sharpe_change * 100)
        elif sharpe_change < 0:
            status = 'EARLY_WARNING'
            health_score = max(60, 100 + sharpe_change * 100)
        else:
            status = 'HEALTHY'
            health_score = min(100, 100 + sharpe_change * 50)

        return {
            'username': username,
            'status': status,
            'health_score': round(health_score, 1),
            'historical_sharpe': round(hist_sharpe, 2),
            'recent_sharpe': round(recent_sharpe, 2),
            'sharpe_change_pct': round(sharpe_change * 100, 1),
            'historical_trades': hist[0],
            'recent_trades': recent[0],
            'recommendation': _get_decay_recommendation(status) if status != 'HEALTHY' else 'Continue monitoring'
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to check trader health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _get_decay_recommendation(status: str) -> str:
    """Get recommendation based on decay status"""
    recommendations = {
        'EARLY_WARNING': 'Increase monitoring frequency',
        'MODERATE': 'Consider reducing index weight by 50%',
        'SEVERE': 'Remove from index consideration',
        'CRITICAL': 'Immediate removal from all indices'
    }
    return recommendations.get(status, 'Continue monitoring')


@app.get("/api/edge/alerts")
async def get_edge_alerts(
    min_decay: float = Query(default=15, ge=0, le=100),
    limit: int = Query(default=20, ge=1, le=100)
):
    """
    Get traders showing edge decay.

    Scans indexed traders and returns those with performance decline.
    Uses a single batch query instead of N+1 pattern for performance.
    """
    try:
        client = get_clickhouse_client()

        # OPTIMIZED: Single query calculates both historical (90d) and recent (30d) metrics
        # This replaces 1000+ individual queries with 1 batch query
        query = f"""
        WITH
        -- Historical metrics (90 days)
        hist AS (
            SELECT
                username,
                avg(notional) AS hist_avg,
                stddevPop(notional) AS hist_std,
                count() AS hist_count
            FROM polybot.aware_global_trades
            WHERE ts >= now() - INTERVAL 90 DAY
              AND username != ''
            GROUP BY username
            HAVING count() >= 30
        ),
        -- Recent metrics (30 days)
        recent AS (
            SELECT
                username,
                avg(notional) AS recent_avg,
                stddevPop(notional) AS recent_std,
                count() AS recent_count
            FROM polybot.aware_global_trades
            WHERE ts >= now() - INTERVAL 30 DAY
              AND username != ''
            GROUP BY username
            HAVING count() >= 10
        )
        SELECT
            h.username,
            h.hist_avg / nullIf(h.hist_std, 0) AS hist_sharpe,
            r.recent_avg / nullIf(r.recent_std, 0) AS recent_sharpe,
            h.hist_count,
            r.recent_count
        FROM hist h
        INNER JOIN recent r ON h.username = r.username
        WHERE h.hist_std > 0 AND r.recent_std > 0
          AND h.hist_avg / h.hist_std > 0  -- Only traders with positive historical Sharpe
        ORDER BY ((h.hist_avg / h.hist_std) - (r.recent_avg / r.recent_std)) / (h.hist_avg / h.hist_std) DESC
        LIMIT 500
        """

        result = client.query(query)

        alerts = []
        for row in result.result_rows:
            username = row[0]
            hist_sharpe = float(row[1]) if row[1] else 0
            recent_sharpe = float(row[2]) if row[2] else 0

            if hist_sharpe > 0:
                decline = ((hist_sharpe - recent_sharpe) / hist_sharpe) * 100
                if decline >= min_decay:
                    alerts.append({
                        'username': username,
                        'decline_pct': round(decline, 1),
                        'historical_sharpe': round(hist_sharpe, 2),
                        'recent_sharpe': round(recent_sharpe, 2)
                    })

        # Already sorted by decline in query, but ensure order
        alerts.sort(key=lambda x: x['decline_pct'], reverse=True)

        return {
            'min_decay_threshold': min_decay,
            'alert_count': len(alerts[:limit]),
            'alerts': alerts[:limit]
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get edge alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ACTIVITY FEED ENDPOINT
# ============================================================================

@app.get("/api/activity/recent")
async def get_recent_activity(
    min_score: int = Query(default=60, ge=0, le=100),
    limit: int = Query(default=50, ge=1, le=200)
):
    """
    Get recent trades from smart money traders.

    Real-time feed of what top traders are doing.
    """
    try:
        client = get_clickhouse_client()

        # Joined on proxy_address, not username: username is empty on nearly
        # every row, so matching on it paired every trade with every score and
        # the feed showed arbitrary trades as if they were high scorers.
        query = f"""
        SELECT
            t.ts,
            t.username,
            t.pseudonym,
            t.proxy_address,
            s.total_score,
            t.market_slug,
            t.title,
            t.side,
            t.outcome,
            t.price,
            t.size,
            t.notional
        FROM polybot.aware_global_trades t
        JOIN (
            SELECT proxy_address, total_score
            FROM polybot.aware_smart_money_scores FINAL
            WHERE total_score >= {min_score}
        ) s ON t.proxy_address = s.proxy_address
        ORDER BY t.ts DESC
        LIMIT {limit}
        """

        result = client.query(query)

        trades = []
        for row in result.result_rows:
            trades.append({
                'timestamp': utc_iso(row[0]) if row[0] else None,
                'username': row[1],
                # username is almost always empty; the pseudonym is what
                # Polymarket actually shows for these accounts.
                'pseudonym': row[2],
                'proxy_address': row[3],
                'smart_money_score': row[4],
                'market_slug': row[5],
                'title': row[6],
                'side': row[7],
                'outcome': row[8],
                'price': round(row[9], 3) if row[9] else None,
                'size': round(row[10], 2) if row[10] else None,
                'notional': round(row[11], 2) if row[11] else None
            })

        return {
            'min_smart_money_score': min_score,
            'trade_count': len(trades),
            'trades': trades
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get recent activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# FUND ENDPOINTS
# ============================================================================

class FundNAV(BaseModel):
    """Fund Net Asset Value"""
    fund_id: str
    nav: float
    capital: float
    position_value: float
    unrealized_pnl: float
    realized_pnl: float
    total_return: float
    open_positions: int
    last_updated: Optional[UtcDatetime]


class FundPosition(BaseModel):
    """A position held by the fund"""
    token_id: str
    market_slug: str
    title: str = ''
    outcome: str
    shares: float
    cost_usd: float
    avg_entry_price: float
    # None when the token has no recent print. A position with no current price
    # cannot be valued, and guessing one would put invented money on the screen.
    current_price: Optional[float] = None
    current_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    priced_at: Optional[str] = None


class FundTrade(BaseModel):
    """A trade executed by the fund"""
    timestamp: UtcDatetime
    source_trader: str
    market_slug: str
    outcome: str
    side: str
    shares: float
    price: float
    notional_usd: float
    status: str


class FundPerformance(BaseModel):
    """Fund performance for a period"""
    period: str
    start_nav: float
    end_nav: float
    return_pct: float
    trades_count: int
    volume_traded: float
    sharpe_ratio: float




@app.get("/api/fund/positions", response_model=list[FundPosition])
async def get_fund_positions(fund_id: str = Query(default="PSI-10")):
    """
    Positions the fund still holds.

    Read from the marked positions the P&L job produces, not from
    aware_fund_positions: nothing writes to that table, so it reported no
    positions for every fund while the funds were plainly trading.

    Only markets that have not resolved appear. A position the job could not
    mark is listed without a price rather than valued at a stale quote.
    """
    try:
        client = get_clickhouse_client()

        # ALPHA-ARB is the complete-set arbitrage engine. It trades directly
        # rather than mirroring anyone, so it has no rows in the executions
        # table; its positions are the open GABAGOOL ones, already netted and
        # marked by the P&L job.
        if fund_id.upper() == 'ALPHA-ARB':
            gab = client.query("""
                SELECT token_id, market_slug, title, outcome, net_shares,
                       cost_usd, avg_price, mark_status, mark_price, value_usd,
                       pnl_usd, mark_age_min
                FROM polybot.aware_strategy_pnl_positions
                WHERE strategy = 'GABAGOOL'
                  AND is_resolved = 0
                  AND calculated_at = (
                      SELECT max(calculated_at)
                      FROM polybot.aware_strategy_pnl_positions
                      WHERE strategy = 'GABAGOOL'
                  )
                ORDER BY cost_usd DESC
            """).result_rows

            out = []
            for (token_id, market_slug, title, outcome, shares, cost_usd,
                 avg_price, mark_status, mark_price, value_usd, pnl_usd,
                 mark_age_min) in gab:
                # STALE means the job found no fresh print, so value_usd and
                # pnl_usd carry no meaning for that row.
                priced = mark_status != 'STALE'
                cost_usd = float(cost_usd)
                out.append(FundPosition(
                    token_id=token_id,
                    market_slug=market_slug,
                    title=title or market_slug,
                    outcome=outcome,
                    shares=round(float(shares), 2),
                    cost_usd=round(cost_usd, 2),
                    avg_entry_price=round(float(avg_price), 4),
                    current_price=round(float(mark_price), 4) if priced else None,
                    current_value=round(float(value_usd), 2) if priced else None,
                    unrealized_pnl=round(float(pnl_usd), 2) if priced else None,
                    unrealized_pnl_pct=(
                        round(100 * float(pnl_usd) / cost_usd, 2)
                        if priced and cost_usd else None
                    ),
                    priced_at=None,
                ))
            return out

        # Mirror funds: the positions actually held come from the simulator's
        # fills, the same rows the P&L job marks — not from the executions
        # table, which records what each fund asked for. A paper order that
        # never filled is an intention, not a position, and counting those made
        # the position list disagree with the P&L above it.
        #
        # Several funds copy the same token, so a fill cannot be attributed to
        # one of them exactly. Each token is apportioned by how many shares each
        # fund requested, which is how the P&L splits it too, so the two agree
        # by construction.
        open_rows = client.query("""
            SELECT token_id, market_slug, title, outcome, net_shares, cost_usd,
                   avg_price, mark_status, mark_price, value_usd, pnl_usd
            FROM polybot.aware_strategy_pnl_positions
            WHERE strategy = 'MIRROR'
              AND is_resolved = 0
              AND calculated_at = (
                  SELECT max(calculated_at)
                  FROM polybot.aware_strategy_pnl_positions
                  WHERE strategy = 'MIRROR'
              )
        """).result_rows

        if not open_rows:
            return []

        weight_rows = client.query("""
            SELECT token_id, fund_id, sum(toFloat64(fund_shares)) AS requested
            FROM polybot.aware_fund_executions
            WHERE token_id IN %(tokens)s
            GROUP BY token_id, fund_id
        """, parameters={'tokens': tuple({r[0] for r in open_rows})}).result_rows

        weights: dict[str, dict[str, float]] = {}
        for token_id, fid, requested in weight_rows:
            weights.setdefault(token_id, {})[fid.upper()] = float(requested)

        wanted = fund_id.upper()
        positions = []
        for (token_id, market_slug, title, outcome, net_shares, cost_usd,
             avg_price, mark_status, mark_price, value_usd, pnl_usd) in open_rows:
            token_weights = weights.get(token_id, {})
            total = sum(token_weights.values())
            requested = token_weights.get(wanted, 0.0)
            if not total or not requested:
                continue
            share = requested / total

            shares = float(net_shares) * share
            cost = float(cost_usd) * share
            priced = mark_status != 'STALE'
            positions.append(FundPosition(
                token_id=token_id,
                market_slug=market_slug,
                title=title or market_slug,
                outcome=outcome,
                shares=round(shares, 2),
                cost_usd=round(cost, 2),
                avg_entry_price=round(float(avg_price), 4),
                current_price=round(float(mark_price), 4) if priced else None,
                current_value=round(float(value_usd) * share, 2) if priced else None,
                unrealized_pnl=round(float(pnl_usd) * share, 2) if priced else None,
                unrealized_pnl_pct=(
                    round(100 * float(pnl_usd) / float(cost_usd), 2)
                    if priced and float(cost_usd) else None
                ),
                priced_at=None,
            ))

        positions.sort(key=lambda p: -p.cost_usd)
        return positions

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get fund positions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/fund/trades", response_model=list[FundTrade])
async def get_fund_trades(
    fund_id: str = Query(default="psi-10-main"),
    limit: int = Query(default=50, ge=1, le=500)
):
    """
    Get recent trades executed by the fund.
    """
    try:
        client = get_clickhouse_client()

        query = f"""
        SELECT
            ts,
            source_trader,
            market_slug,
            outcome,
            side,
            shares,
            price,
            notional_usd,
            status
        FROM polybot.aware_fund_trades
        WHERE fund_id = %(fund_id)s
        ORDER BY ts DESC
        LIMIT {limit}
        """

        result = client.query(query, parameters={'fund_id': fund_id})

        trades = []
        for row in result.result_rows:
            trades.append(FundTrade(
                timestamp=row[0],
                source_trader=row[1],
                market_slug=row[2],
                outcome=row[3],
                side=row[4],
                shares=float(row[5]),
                price=float(row[6]),
                notional_usd=float(row[7]),
                status=row[8]
            ))

        return trades

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get fund trades: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/fund/performance", response_model=list[FundPerformance])
async def get_fund_performance(fund_id: str = Query(default="psi-10-main")):
    """
    Get fund performance across different time periods.
    """
    try:
        client = get_clickhouse_client()

        query = """
        SELECT
            period,
            start_nav,
            end_nav,
            return_pct,
            trades_count,
            volume_traded,
            sharpe_ratio
        FROM polybot.aware_fund_performance FINAL
        WHERE fund_id = %(fund_id)s
        ORDER BY
            CASE period
                WHEN 'daily' THEN 1
                WHEN 'weekly' THEN 2
                WHEN 'monthly' THEN 3
                WHEN 'all_time' THEN 4
            END
        """

        result = client.query(query, parameters={'fund_id': fund_id})

        performance = []
        for row in result.result_rows:
            performance.append(FundPerformance(
                period=row[0],
                start_nav=float(row[1]),
                end_nav=float(row[2]),
                return_pct=float(row[3]),
                trades_count=int(row[4]),
                volume_traded=float(row[5]),
                sharpe_ratio=float(row[6])
            ))

        return performance

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get fund performance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/fund/index")
async def get_fund_index(index_type: str = Query(default="PSI-10")):
    """
    Get the current PSI index constituents and weights.

    Returns traders in the index with their weights.
    """
    try:
        client = get_clickhouse_client()

        # username is often empty, so also return proxy_address and the
        # pseudonym from the trader profile to identify the trader.
        query = """
        SELECT
            i.username,
            i.proxy_address,
            p.pseudonym,
            i.weight,
            i.total_score,
            i.sharpe_ratio,
            i.strategy_type,
            i.rebalanced_at
        FROM polybot.v_psi_index_current AS i
        LEFT JOIN (
            SELECT proxy_address, pseudonym
            FROM polybot.aware_trader_profiles FINAL
        ) AS p ON i.proxy_address = p.proxy_address
        WHERE i.index_type = %(index_type)s
        ORDER BY i.weight DESC
        """

        result = client.query(query, parameters={'index_type': index_type})

        constituents = []
        for i, row in enumerate(result.result_rows):
            constituents.append({
                'rank': i + 1,
                'username': row[0],
                'proxy_address': row[1],
                'pseudonym': row[2],
                'weight': round(float(row[3]) * 100, 2),  # As percentage
                'smart_money_score': float(row[4]),
                'sharpe_ratio': float(row[5]),
                'strategy_type': row[6],
                'rebalanced_at': utc_iso(row[7]) if row[7] else None
            })

        return {
            'index_type': index_type,
            'constituent_count': len(constituents),
            'total_weight': sum(c['weight'] for c in constituents),
            'constituents': constituents
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get fund index: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class FundInfo(BaseModel):
    """Fund information"""
    fund_id: str
    fund_type: str  # MIRROR or ACTIVE
    description: str
    strategy: str
    capital_usd: Optional[float]
    is_active: bool


class FundExecution(BaseModel):
    """A signal execution by the fund"""
    signal_id: str
    fund_id: str
    trader_username: str
    market_slug: str
    outcome: str
    signal_type: str
    trader_shares: float
    fund_shares: float
    execution_price: float
    detected_at: UtcDatetime
    executed_at: UtcDatetime


@app.get("/api/fund/list", response_model=list[FundInfo])
async def list_funds():
    """
    List all available fund types.

    Returns both MIRROR funds (PSI indexes) and ACTIVE funds (ALPHA strategies).
    """
    # Static fund definitions - these match FundType.java
    funds = [
        # MIRROR funds (passive, mirror top traders)
        FundInfo(
            fund_id="PSI-10",
            fund_type="MIRROR",
            description="Top 10 Smart Money traders",
            strategy="Mirror positions of top 10 replicable traders by Smart Money Score",
            capital_usd=None,
            is_active=True
        ),
        FundInfo(
            fund_id="PSI-25",
            fund_type="MIRROR",
            description="Top 25 Smart Money traders",
            strategy="Broader index mirroring top 25 traders",
            capital_usd=None,
            is_active=False
        ),
        FundInfo(
            fund_id="PSI-SPORTS",
            fund_type="MIRROR",
            description="Top sports betting traders",
            strategy="Mirror top traders specializing in sports markets",
            capital_usd=None,
            is_active=False
        ),
        FundInfo(
            fund_id="PSI-CRYPTO",
            fund_type="MIRROR",
            description="Top crypto price traders",
            strategy="Mirror top traders in crypto price prediction markets",
            capital_usd=None,
            is_active=False
        ),
        FundInfo(
            fund_id="PSI-POLITICS",
            fund_type="MIRROR",
            description="Top political market traders",
            strategy="Mirror top traders in political prediction markets",
            capital_usd=None,
            is_active=False
        ),
        # ACTIVE funds (proprietary strategies)
        FundInfo(
            fund_id="ALPHA-ARB",
            fund_type="ACTIVE",
            description="Complete-set arbitrage strategy",
            strategy="Runs gabagool22-style arbitrage on Up/Down binary markets",
            capital_usd=None,
            is_active=True
        ),
        FundInfo(
            fund_id="ALPHA-INSIDER",
            fund_type="ACTIVE",
            description="Insider signal following",
            strategy="Trades based on insider detection signals",
            capital_usd=None,
            is_active=False
        ),
        FundInfo(
            fund_id="ALPHA-EDGE",
            fund_type="ACTIVE",
            description="Multi-strategy alpha fund",
            strategy="Combines arbitrage, insider signals, and momentum",
            capital_usd=None,
            is_active=False
        ),
    ]

    return funds


@app.get("/api/fund/executions", response_model=list[FundExecution])
async def get_fund_executions(
    fund_id: str = Query(default="PSI-10"),
    limit: int = Query(default=50, ge=1, le=500)
):
    """
    Get fund executions (signal mirrors).

    Shows the signals from tracked traders and how the fund executed them.
    """
    try:
        client = get_clickhouse_client()

        query = f"""
        SELECT
            signal_id,
            fund_id,
            trader_username,
            market_slug,
            outcome,
            signal_type,
            trader_shares,
            fund_shares,
            execution_price,
            detected_at,
            executed_at
        FROM polybot.aware_fund_executions
        WHERE fund_id = %(fund_id)s
        ORDER BY executed_at DESC
        LIMIT {limit}
        """

        result = client.query(query, parameters={'fund_id': fund_id})

        executions = []
        for row in result.result_rows:
            executions.append(FundExecution(
                signal_id=row[0],
                fund_id=row[1],
                trader_username=row[2],
                market_slug=row[3],
                outcome=row[4],
                signal_type=row[5],
                trader_shares=float(row[6]),
                fund_shares=float(row[7]),
                execution_price=float(row[8]),
                detected_at=row[9],
                executed_at=row[10]
            ))

        return executions

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get fund executions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# INSIDER ALERTS ENDPOINTS
# ============================================================================

class InsiderAlert(BaseModel):
    """An insider activity alert"""
    signal_type: str
    severity: str
    market_slug: str
    market_question: str
    description: str
    confidence: float
    direction: str
    total_volume_usd: float
    num_traders: int
    detected_at: UtcDatetime
    traders_involved: list[str]


class InsiderAlertsResponse(BaseModel):
    """Response containing insider alerts"""
    lookback_hours: int
    alert_count: int
    alerts: list[InsiderAlert]


@app.get("/api/insider/alerts", response_model=InsiderAlertsResponse)
@limiter.limit("30/minute")
async def get_insider_alerts(
    request: Request,
    hours: int = Query(default=48, ge=1, le=168),
    min_confidence: float = Query(default=0.3, ge=0.0, le=1.0),
    api_key: Optional[str] = Depends(optional_api_key)
):
    """
    Get insider activity alerts.

    Scans for suspicious trading patterns that may indicate insider knowledge:
    - NEW_ACCOUNT_WHALE: New accounts making large bets on obscure markets
    - VOLUME_SPIKE: Unusual volume spikes before news events
    - SMART_MONEY_DIVERGENCE: Top traders betting against market consensus
    - WHALE_ANOMALY: Known whales entering unusual market categories
    """
    try:
        client = get_clickhouse_client()

        # Check if the insider alerts table exists
        try:
            result = client.query(f"""
                SELECT
                    signal_type,
                    severity,
                    market_slug,
                    market_question,
                    description,
                    confidence,
                    direction,
                    total_volume_usd,
                    num_traders,
                    detected_at,
                    traders_involved
                FROM polybot.aware_insider_alerts FINAL
                WHERE detected_at >= now() - INTERVAL {hours} HOUR
                  AND confidence >= {min_confidence}
                ORDER BY detected_at DESC, severity DESC
                LIMIT 100
            """)

            alerts = []
            for row in result.result_rows:
                # Parse traders_involved (stored as comma-separated string)
                traders = row[10].split(',') if row[10] else []
                traders = [t.strip() for t in traders if t.strip()]

                alerts.append(InsiderAlert(
                    signal_type=row[0],
                    severity=row[1],
                    market_slug=row[2],
                    market_question=row[3] or '',
                    description=row[4] or '',
                    confidence=float(row[5]),
                    direction=row[6],
                    total_volume_usd=float(row[7]),
                    num_traders=int(row[8]),
                    detected_at=row[9],
                    traders_involved=traders
                ))

            return InsiderAlertsResponse(
                lookback_hours=hours,
                alert_count=len(alerts),
                alerts=alerts
            )

        except Exception as table_err:
            # Table doesn't exist yet - return empty response
            logger.warning(f"Insider alerts table may not exist: {table_err}")
            return InsiderAlertsResponse(
                lookback_hours=hours,
                alert_count=0,
                alerts=[]
            )

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get insider alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/insider/scan")
async def scan_for_insider_activity(hours: int = Query(default=24, ge=1, le=72)):
    """
    Trigger an insider activity scan.

    This endpoint runs the InsiderDetector to find new suspicious activity.
    Note: In production, this would be called by a scheduled job.
    """
    try:
        # Import the insider detector
        from insider_detector import InsiderDetector

        client = get_clickhouse_client()
        detector = InsiderDetector(client)

        # Run the scan
        alerts = detector.scan_for_insider_activity(lookback_hours=hours)

        return {
            'status': 'success',
            'alerts_found': len(alerts),
            'lookback_hours': hours,
            'alerts': [
                {
                    'signal_type': a.signal_type.value,
                    'severity': a.severity.value,
                    'market_slug': a.market_slug,
                    'confidence': a.confidence,
                    'direction': a.direction
                }
                for a in alerts
            ]
        }

    except ImportError:
        return {
            'status': 'error',
            'message': 'InsiderDetector module not available'
        }
    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to scan for insider activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ML ENRICHMENT ENDPOINTS
# ============================================================================

class MLClusterSummary(BaseModel):
    """Summary of a Strategy DNA cluster"""
    cluster_id: int
    strategy_cluster: str
    trader_count: int
    anomaly_count: int
    avg_anomaly_score: float


class MLTraderEnrichment(BaseModel):
    """ML enrichment data for a trader"""
    proxy_address: str
    username: str
    cluster_id: int
    strategy_cluster: str
    cluster_description: str
    is_anomaly: bool
    anomaly_score: float
    anomaly_type: str
    updated_at: Optional[UtcDatetime]


class MLAnomalyEntry(BaseModel):
    """An anomalous trader entry"""
    proxy_address: str
    username: str
    strategy_cluster: str
    anomaly_score: float
    anomaly_type: str
    smart_money_score: Optional[float]
    total_volume: Optional[float]


@app.get("/api/ml/clusters", response_model=list[MLClusterSummary])
async def get_ml_clusters():
    """
    Get Strategy DNA cluster distribution.

    Shows how traders are grouped by behavioral patterns.
    """
    try:
        client = get_clickhouse_client()

        result = client.query("""
            SELECT
                cluster_id,
                strategy_cluster,
                count() AS trader_count,
                sum(is_anomaly) AS anomaly_count,
                avg(anomaly_score) AS avg_anomaly_score
            FROM polybot.aware_ml_enrichment FINAL
            GROUP BY cluster_id, strategy_cluster
            ORDER BY trader_count DESC
        """)

        clusters = []
        for row in result.result_rows:
            clusters.append(MLClusterSummary(
                cluster_id=int(row[0]),
                strategy_cluster=row[1] or 'UNKNOWN',
                trader_count=int(row[2]),
                anomaly_count=int(row[3]),
                avg_anomaly_score=float(row[4]) if row[4] else 0.0
            ))

        return clusters

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get ML clusters: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ml/anomalies", response_model=list[MLAnomalyEntry])
async def get_ml_anomalies(
    limit: int = Query(default=50, ge=1, le=200),
    anomaly_type: Optional[str] = Query(default=None)
):
    """
    Get traders flagged as anomalous by ML models.

    Anomaly types:
    - ISOLATION: Detected by Isolation Forest (global outlier)
    - RECONSTRUCTION: Detected by Autoencoder (behavioral anomaly)
    - BOTH: Flagged by both models (high confidence anomaly)
    """
    try:
        client = get_clickhouse_client()

        where_clause = "is_anomaly = 1"
        if anomaly_type:
            safe_type = anomaly_type.upper()
            if safe_type in ('ISOLATION', 'RECONSTRUCTION', 'BOTH'):
                where_clause += f" AND anomaly_type = '{safe_type}'"

        query = f"""
            SELECT
                ml.proxy_address,
                ml.username,
                ml.strategy_cluster,
                ml.anomaly_score,
                ml.anomaly_type,
                s.total_score AS smart_money_score,
                p.total_volume_usd AS total_volume
            FROM (SELECT * FROM polybot.aware_ml_enrichment FINAL) AS ml
            LEFT JOIN (SELECT * FROM polybot.aware_smart_money_scores FINAL) AS s
                ON ml.proxy_address = s.proxy_address
            LEFT JOIN (SELECT * FROM polybot.aware_trader_profiles FINAL) AS p
                ON ml.proxy_address = p.proxy_address
            WHERE {where_clause}
            ORDER BY ml.anomaly_score ASC
            LIMIT {limit}
        """

        result = client.query(query)

        anomalies = []
        for row in result.result_rows:
            anomalies.append(MLAnomalyEntry(
                proxy_address=row[0],
                username=row[1] or '',
                strategy_cluster=row[2] or 'UNKNOWN',
                anomaly_score=float(row[3]) if row[3] else 0.0,
                anomaly_type=row[4] or 'UNKNOWN',
                smart_money_score=float(row[5]) if row[5] else None,
                total_volume=float(row[6]) if row[6] else None
            ))

        return anomalies

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get ML anomalies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ml/trader/{identifier}", response_model=MLTraderEnrichment)
async def get_trader_ml_enrichment(identifier: str):
    """
    Get ML enrichment data for a specific trader.

    Looks up by username or proxy_address.
    """
    try:
        client = get_clickhouse_client()

        result = client.query("""
            SELECT
                proxy_address,
                username,
                cluster_id,
                strategy_cluster,
                cluster_description,
                is_anomaly,
                anomaly_score,
                anomaly_type,
                updated_at
            FROM polybot.aware_ml_enrichment FINAL
            WHERE lower(username) = lower(%(identifier)s)
               OR lower(proxy_address) = lower(%(identifier)s)
            LIMIT 1
        """, parameters={'identifier': identifier})

        if not result.result_rows:
            raise HTTPException(status_code=404, detail=f"ML enrichment not found for '{identifier}'")

        row = result.result_rows[0]
        return MLTraderEnrichment(
            proxy_address=row[0],
            username=row[1] or '',
            cluster_id=int(row[2]),
            strategy_cluster=row[3] or 'UNKNOWN',
            cluster_description=row[4] or '',
            is_anomaly=bool(row[5]),
            anomaly_score=float(row[6]) if row[6] else 0.0,
            anomaly_type=row[7] or 'NORMAL',
            updated_at=row[8]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get trader ML enrichment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pnl/summary")
async def get_pnl_summary():
    """
    Paper-trading P&L, aggregated across strategies.

    Reads the latest snapshot written by the analytics strategy_pnl job. Returns
    zeros with has_data=false before the first snapshot exists, so callers can
    render a placeholder rather than an error.
    """
    try:
        client = get_clickhouse_client()

        result = client.query("""
            SELECT
                strategy,
                realized_pnl,
                unrealized_pnl,
                total_pnl,
                cost_usd,
                stale_cost_usd,
                positions,
                positions_resolved,
                calculated_at
            FROM polybot.aware_strategy_pnl
            WHERE calculated_at = (SELECT max(calculated_at) FROM polybot.aware_strategy_pnl)
            ORDER BY strategy
        """)

        rows = result.result_rows
        if not rows:
            return {
                "has_data": False,
                "mode": os.getenv("HFT_MODE", "PAPER").upper(),
                "total_pnl": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "roi_pct": 0.0,
                "positions": 0,
                "calculated_at": None,
                "strategies": [],
            }

        strategies = [
            {
                "strategy": r[0],
                "realized_pnl": float(r[1]),
                "unrealized_pnl": float(r[2]),
                "total_pnl": float(r[3]),
                "positions": int(r[6]),
                "positions_resolved": int(r[7]),
            }
            for r in rows
        ]

        total_pnl = sum(s["total_pnl"] for s in strategies)
        # Cost of what could actually be priced; stale positions are excluded
        # from the P&L above, so counting them here would understate the ROI.
        priced_cost = sum(float(r[4]) - float(r[5]) for r in rows)

        return {
            "has_data": True,
            # Labels the figure honestly: simulated fills or real money.
            "mode": os.getenv("HFT_MODE", "PAPER").upper(),
            "total_pnl": total_pnl,
            "realized_pnl": sum(s["realized_pnl"] for s in strategies),
            "unrealized_pnl": sum(s["unrealized_pnl"] for s in strategies),
            "roi_pct": (total_pnl / priced_cost * 100) if priced_cost else 0.0,
            "positions": sum(s["positions"] for s in strategies),
            "calculated_at": utc_iso(rows[0][8]),
            "strategies": strategies,
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get P&L summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pnl/history")
async def get_pnl_history(days: int = Query(default=7, ge=1, le=90)):
    """
    P&L over time, one series per strategy.

    Built from the snapshots the analytics job writes each run, so the
    resolution is however often the pipeline cycles. Returns points shaped for
    charting: one entry per timestamp with a key per strategy.
    """
    try:
        client = get_clickhouse_client()

        result = client.query("""
            SELECT
                calculated_at,
                strategy,
                total_pnl
            FROM polybot.aware_strategy_pnl
            WHERE calculated_at >= now() - INTERVAL %(days)s DAY
            ORDER BY calculated_at, strategy
        """, parameters={'days': days})

        # Pivot to one row per timestamp so a chart can read it directly.
        points: dict = {}
        strategies: list = []
        for calculated_at, strategy, total_pnl in result.result_rows:
            key = utc_iso(calculated_at)
            points.setdefault(key, {'timestamp': key})
            points[key][strategy] = round(float(total_pnl), 2)
            if strategy not in strategies:
                strategies.append(strategy)

        series = sorted(points.values(), key=lambda p: p['timestamp'])

        return {
            'days': days,
            'strategies': strategies,
            'point_count': len(series),
            'points': series,
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get P&L history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Capital allocated to each fund, mirroring hft.multi-fund in
# strategy-service/src/main/resources/application-production.yaml. Duplicated
# rather than read from the strategy service, which exposes no endpoint for it;
# if the percentages change there, change them here too.
# Mirrors the multi-fund allocation in strategy-service's application-*.yaml.
# Keep the two in step: this is what the dashboard reports as allocated, and a
# fund missing here is a fund the dashboard will not list at all.
#
# Declared in display order — the mirror funds first, broad before sectorial,
# then the active ones. Every list of funds is rendered in this order, so a
# fund keeps its place instead of moving around as the numbers change.
FUND_CAPITAL_PCT = {
    'PSI-10': 15,
    'PSI-25': 10,
    'PSI-CRYPTO': 10,
    'PSI-POLITICS': 10,
    'PSI-SPORTS': 5,
    'PSI-ALPHA': 10,
    'ALPHA-ARB': 15,
    'ALPHA-INSIDER': 17,
    'ALPHA-EDGE': 8,
}

FUND_DISPLAY_ORDER = tuple(FUND_CAPITAL_PCT)


def _open_cost_by_fund(client) -> dict:
    """
    What each fund currently has at risk, per fund id.

    Distinct from the cost_usd on aware_fund_pnl, which accumulates over every
    position the fund has ever taken and so keeps growing as markets settle.
    That figure is the base the ROI is measured against; this one is the money
    presently in the market, which is what belongs next to the allocation.
    """
    open_cost: dict = {}

    # STALE positions are excluded throughout. A position the job could not
    # mark has had no print for hours, which on a 5- or 15-minute market means
    # it settled long ago and the resolution simply has not been recorded yet.
    # Counting those as money in the market is what put $36k of exposure on a
    # $15k fund. The P&L already leaves them out for the same reason, so the
    # two figures agree.
    #
    # ALPHA-ARB trades directly, so its open cost is the GABAGOOL side outright.
    gab = client.query("""
        SELECT sum(cost_usd)
        FROM polybot.aware_strategy_pnl_positions
        WHERE strategy = 'GABAGOOL' AND is_resolved = 0
          AND mark_status != 'STALE'
          AND calculated_at = (
              SELECT max(calculated_at) FROM polybot.aware_strategy_pnl_positions
              WHERE strategy = 'GABAGOOL'
          )
    """).result_rows
    if gab and gab[0][0]:
        open_cost['ALPHA-ARB'] = float(gab[0][0])

    # Mirror funds share tokens, so each open position is apportioned by
    # requested shares — the same split the P&L uses, so the two agree.
    rows = client.query("""
        SELECT token_id, cost_usd
        FROM polybot.aware_strategy_pnl_positions
        WHERE strategy = 'MIRROR' AND is_resolved = 0
          AND mark_status != 'STALE'
          AND calculated_at = (
              SELECT max(calculated_at) FROM polybot.aware_strategy_pnl_positions
              WHERE strategy = 'MIRROR'
          )
    """).result_rows
    if not rows:
        return open_cost

    weights: dict = {}
    for token_id, fid, requested in client.query("""
        SELECT token_id, fund_id, sum(toFloat64(fund_shares))
        FROM polybot.aware_fund_executions
        WHERE token_id IN %(tokens)s
        GROUP BY token_id, fund_id
    """, parameters={'tokens': tuple({r[0] for r in rows})}).result_rows:
        weights.setdefault(token_id, {})[fid.upper()] = float(requested)

    for token_id, cost_usd in rows:
        token_weights = weights.get(token_id, {})
        total = sum(token_weights.values())
        if not total:
            continue
        for fid, requested in token_weights.items():
            open_cost[fid] = open_cost.get(fid, 0.0) + float(cost_usd) * requested / total

    return open_cost


def _fund_sort_key(fund_id: str) -> int:
    """Position in FUND_DISPLAY_ORDER; anything unlisted sorts to the end."""
    upper = fund_id.upper()
    return (FUND_DISPLAY_ORDER.index(upper)
            if upper in FUND_DISPLAY_ORDER else len(FUND_DISPLAY_ORDER))

# Matches the descriptions in FundType.java.
FUND_DESCRIPTIONS = {
    'PSI-10': 'Mirrors the 10 highest-scoring traders',
    'PSI-25': 'Mirrors the top 25, more diversified',
    'PSI-CRYPTO': 'Mirrors the best traders in crypto markets',
    'PSI-POLITICS': 'Mirrors the best traders in political markets',
    'PSI-SPORTS': 'Mirrors the best traders in sports markets',
    'PSI-ALPHA': 'Mirrors the highest alpha generators',
    'ALPHA-ARB': 'Complete-set arbitrage, trades directly',
    'ALPHA-INSIDER': 'Follows unusual-activity signals',
    'ALPHA-EDGE': 'Multi-strategy, depends on the ML models',
}


def _allocated_capital(fund_id: str) -> float:
    """The simulated capital this fund is allowed to deploy."""
    total = float(os.getenv('TOTAL_CAPITAL_USD', '100000'))
    return total * FUND_CAPITAL_PCT.get(fund_id.upper(), 0) / 100


@app.get("/api/fund/pnl")
async def get_fund_pnl(fund_id: str = Query(...)):
    """
    P&L for one fund, from the latest snapshot.

    Apportioned, not exact: several funds copy the same token, so each token's
    result is split by how many shares each fund asked for. Fine for comparing
    funds, not an exact ledger — the response says so.
    """
    try:
        client = get_clickhouse_client()
        fund = fund_id.upper()

        # ALPHA-ARB is the complete-set arbitrage engine, which trades directly
        # rather than mirroring anyone, so it has no rows in aware_fund_pnl.
        # Its figures live under the GABAGOOL strategy, and unlike the mirror
        # split those are exact rather than apportioned.
        if fund == 'ALPHA-ARB':
            direct = client.query("""
                SELECT positions, cost_usd - stale_cost_usd, realized_pnl,
                       unrealized_pnl, total_pnl, roi_pct, calculated_at
                FROM polybot.aware_strategy_pnl
                WHERE strategy = 'GABAGOOL'
                ORDER BY calculated_at DESC
                LIMIT 1
            """)
            if direct.result_rows:
                r = direct.result_rows[0]
                return {
                    'fund_id': fund,
                    'has_data': True,
                    'apportioned': False,
                    'allocated_capital': _allocated_capital(fund),
                    'positions': int(r[0]),
                    # Cumulative across every position ever taken; the ROI
                    # below is measured against it.
                    'cost_usd': float(r[1]),
                    # What is in the market right now.
                    'open_cost_usd': round(_open_cost_by_fund(client).get(fund, 0.0), 2),
                    'realized_pnl': float(r[2]),
                    'unrealized_pnl': float(r[3]),
                    'total_pnl': float(r[4]),
                    'roi_pct': float(r[5]),
                    'calculated_at': utc_iso(r[6]) if r[6] else None,
                }

        result = client.query("""
            SELECT positions, cost_usd, realized_pnl, unrealized_pnl,
                   total_pnl, roi_pct, calculated_at
            FROM polybot.aware_fund_pnl
            WHERE fund_id = %(fund_id)s
              AND calculated_at = (
                  SELECT max(calculated_at) FROM polybot.aware_fund_pnl
              )
            LIMIT 1
        """, parameters={'fund_id': fund})

        if not result.result_rows:
            return {
                'fund_id': fund,
                'has_data': False,
                'apportioned': True,
                'allocated_capital': _allocated_capital(fund),
                'positions': 0,
                'cost_usd': 0.0,
                'realized_pnl': 0.0,
                'unrealized_pnl': 0.0,
                'total_pnl': 0.0,
                'roi_pct': 0.0,
                'calculated_at': None,
            }

        r = result.result_rows[0]
        return {
            'fund_id': fund,
            'has_data': True,
            'apportioned': True,
            'allocated_capital': _allocated_capital(fund),
            'positions': int(r[0]),
            # Cumulative across every position ever taken; the ROI below is
            # measured against it.
            'cost_usd': float(r[1]),
            # What is in the market right now.
            'open_cost_usd': round(_open_cost_by_fund(client).get(fund, 0.0), 2),
            'realized_pnl': float(r[2]),
            'unrealized_pnl': float(r[3]),
            'total_pnl': float(r[4]),
            'roi_pct': float(r[5]),
            'calculated_at': utc_iso(r[6]) if r[6] else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get fund P&L: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/fund/summary")
async def get_funds_summary():
    """
    One row per fund with what it was allocated and what it has actually done.

    Replaces reading aware_fund_summary for this purpose: that table is fed by
    the NAV calculator, which derives everything from investor deposits and a
    positions table nothing writes, so it reports NAV 1.0 and zero AUM for
    every fund regardless of activity.
    """
    try:
        client = get_clickhouse_client()

        pnl_rows = client.query("""
            SELECT fund_id, positions, cost_usd, realized_pnl,
                   unrealized_pnl, total_pnl, roi_pct
            FROM polybot.aware_fund_pnl
            WHERE calculated_at = (SELECT max(calculated_at) FROM polybot.aware_fund_pnl)
        """).result_rows
        by_fund = {r[0]: r for r in pnl_rows}

        # ALPHA-ARB trades directly rather than mirroring, so its figures come
        # from the strategy table instead, where they are exact.
        gabagool = client.query("""
            SELECT positions, cost_usd - stale_cost_usd, realized_pnl,
                   unrealized_pnl, total_pnl, roi_pct
            FROM polybot.aware_strategy_pnl
            WHERE strategy = 'GABAGOOL'
            ORDER BY calculated_at DESC
            LIMIT 1
        """).result_rows

        open_cost = _open_cost_by_fund(client)

        funds = []
        for fund_id, pct in FUND_CAPITAL_PCT.items():
            row = by_fund.get(fund_id)
            exact = False
            if fund_id == 'ALPHA-ARB' and gabagool:
                row = (fund_id,) + tuple(gabagool[0])
                exact = True

            allocated = _allocated_capital(fund_id)
            open_now = round(open_cost.get(fund_id, 0.0), 2)
            if row:
                funds.append({
                    'fund_id': fund_id,
                    'category': 'MIRROR' if fund_id.startswith('PSI') else 'ACTIVE',
                    'description': FUND_DESCRIPTIONS.get(fund_id, ''),
                    'allocated_capital': allocated,
                    'has_data': True,
                    'apportioned': not exact,
                    'positions': int(row[1]),
                    # Cumulative cost of every position taken. The ROI is
                    # measured against this, which is why it can exceed the
                    # allocation: capital is recycled as markets settle.
                    'invested': float(row[2]),
                    # Currently at risk — the figure that pairs with allocated.
                    'open_cost_usd': open_now,
                    'realized_pnl': float(row[3]),
                    'unrealized_pnl': float(row[4]),
                    'total_pnl': float(row[5]),
                    'roi_pct': float(row[6]),
                })
            else:
                funds.append({
                    'fund_id': fund_id,
                    'category': 'MIRROR' if fund_id.startswith('PSI') else 'ACTIVE',
                    'description': FUND_DESCRIPTIONS.get(fund_id, ''),
                    'allocated_capital': allocated,
                    'has_data': False,
                    'apportioned': True,
                    'positions': 0, 'invested': 0.0, 'open_cost_usd': 0.0,
                    'realized_pnl': 0.0,
                    'unrealized_pnl': 0.0, 'total_pnl': 0.0, 'roi_pct': 0.0,
                })

        return {
            'total_capital': float(os.getenv('TOTAL_CAPITAL_USD', '100000')),
            'total_invested': sum(f['invested'] for f in funds),
            'total_open_cost': sum(f['open_cost_usd'] for f in funds),
            'total_pnl': sum(f['total_pnl'] for f in funds),
            'funds': sorted(funds, key=lambda f: _fund_sort_key(f['fund_id'])),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get funds summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/fund/pnl-history")
async def get_fund_pnl_history(
    fund_id: str = Query(...),
    days: int = Query(default=7, ge=1, le=365),
):
    """
    P&L over time for one fund, from the aware_fund_pnl snapshots.

    Replaces charting nav_per_share, which is 1.0 at every point for every fund
    because the NAV calculation has no deposits or positions to work from.
    """
    try:
        client = get_clickhouse_client()
        fund = fund_id.upper()

        # ALPHA-ARB trades directly rather than mirroring, so its history lives
        # under the GABAGOOL strategy.
        if fund == 'ALPHA-ARB':
            rows = client.query("""
                SELECT calculated_at, total_pnl, realized_pnl, unrealized_pnl
                FROM polybot.aware_strategy_pnl
                WHERE strategy = 'GABAGOOL'
                  AND calculated_at >= now() - INTERVAL %(days)s DAY
                ORDER BY calculated_at
            """, parameters={'days': days}).result_rows
        else:
            rows = client.query("""
                SELECT calculated_at, total_pnl, realized_pnl, unrealized_pnl
                FROM polybot.aware_fund_pnl
                WHERE fund_id = %(fund_id)s
                  AND calculated_at >= now() - INTERVAL %(days)s DAY
                ORDER BY calculated_at
            """, parameters={'fund_id': fund, 'days': days}).result_rows

        return {
            'fund_id': fund,
            'days': days,
            'point_count': len(rows),
            'points': [
                {
                    'timestamp': utc_iso(r[0]),
                    'total_pnl': round(float(r[1]), 2),
                    'realized_pnl': round(float(r[2]), 2),
                    'unrealized_pnl': round(float(r[3]), 2),
                }
                for r in rows
            ],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get fund P&L history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/fund/comparison")
async def get_fund_comparison(days: int = Query(default=30, ge=1, le=365)):
    """
    ROI over time for every fund that has traded, for comparing them.

    ROI rather than dollars: the funds are allocated different amounts and
    deploy different volumes, so absolute P&L would just rank them by size.
    Funds with no activity are omitted rather than drawn as a flat line, which
    would read as "traded and made nothing".
    """
    try:
        client = get_clickhouse_client()

        rows = client.query("""
            SELECT calculated_at, fund_id, roi_pct
            FROM polybot.aware_fund_pnl
            WHERE calculated_at >= now() - INTERVAL %(days)s DAY
            ORDER BY calculated_at
        """, parameters={'days': days}).result_rows

        # ALPHA-ARB trades directly, so its series lives under the strategy.
        arb = client.query("""
            SELECT calculated_at, 'ALPHA-ARB', roi_pct
            FROM polybot.aware_strategy_pnl
            WHERE strategy = 'GABAGOOL'
              AND calculated_at >= now() - INTERVAL %(days)s DAY
            ORDER BY calculated_at
        """, parameters={'days': days}).result_rows

        points: dict = {}
        funds: list = []
        for calculated_at, fund_id, roi in list(rows) + list(arb):
            key = utc_iso(calculated_at)
            points.setdefault(key, {'timestamp': key})
            points[key][fund_id] = round(float(roi), 2)
            if fund_id not in funds:
                funds.append(fund_id)

        return {
            'days': days,
            'funds': sorted(funds, key=_fund_sort_key),
            'point_count': len(points),
            'points': sorted(points.values(), key=lambda p: p['timestamp']),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get fund comparison: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ml/health")
async def get_ml_health():
    """
    Get ML pipeline health status.

    Returns status matching MLHealthResponse interface:
    - status: 'healthy' | 'degraded' | 'unhealthy'
    - model_version: string
    - scoring_method: 'ml_ensemble' | 'rule_based'
    - traders_scored: number
    - tier_distribution: Record<string, number>
    - drift_status: 'normal' | 'warning' | 'critical'
    - drift_ratio: number
    - drifted_features: string[]
    """
    try:
        client = get_clickhouse_client()

        # Get ML enrichment stats
        enrichment_result = client.query("""
            SELECT
                count() AS total_enriched,
                countIf(is_anomaly = 1) AS anomalies,
                uniqExact(strategy_cluster) AS num_clusters,
                max(updated_at) AS last_update,
                dateDiff('minute', max(updated_at), now()) AS minutes_ago
            FROM polybot.aware_ml_enrichment FINAL
        """)

        # Get scoring stats and model version from ML scores
        scores_result = client.query("""
            SELECT
                count() AS traders_scored,
                max(model_version) AS model_version,
                max(calculated_at) AS last_scoring_at
            FROM polybot.aware_ml_scores FINAL
        """)

        # Get tier distribution from smart money scores
        tier_result = client.query("""
            SELECT
                tier,
                count() AS count
            FROM polybot.aware_smart_money_scores FINAL
            WHERE tier != ''
            GROUP BY tier
        """)

        tier_distribution = {}
        for row in tier_result.result_rows:
            tier_distribution[row[0]] = int(row[1])

        # Ensure all tiers are present
        for tier in ['DIAMOND', 'GOLD', 'SILVER', 'BRONZE']:
            if tier not in tier_distribution:
                tier_distribution[tier] = 0

        # How long since the ML enrichment last wrote anything. None when the
        # table has never had a row, which is the case here: the ml/models
        # package is absent from the repository, so nothing produces enrichment.
        # That is a missing component, not a stale one, and reporting it as
        # 9999 minutes of staleness turned it into a permanent "drift critical"
        # against a baseline that has never existed.
        # Guarded on the row count, not on the age. max() over an empty table
        # returns the epoch, so dateDiff hands back ~29.8 million minutes, which
        # is not staleness — it is emptiness wearing a number.
        enrichment_minutes_ago = None
        if enrichment_result.result_rows:
            e_row = enrichment_result.result_rows[0]
            if int(e_row[0] or 0) > 0 and e_row[4]:
                enrichment_minutes_ago = int(e_row[4])

        # Parse scoring stats
        traders_scored = 0
        model_version = 'rule_based_v1'
        last_scoring_at = None
        if scores_result.result_rows:
            s_row = scores_result.result_rows[0]
            traders_scored = int(s_row[0]) if s_row[0] else 0
            model_version = s_row[1] if s_row[1] else 'rule_based_v1'
            last_scoring_at = utc_iso(s_row[2]) if s_row[2] else None

        # Determine scoring method from model version
        scoring_method = 'ml_ensemble' if 'ensemble' in model_version.lower() else 'rule_based'

        # Health is judged on the scoring, which is what actually runs and what
        # every downstream index depends on. It was judged on the enrichment
        # table before, so the badge read "degraded" while scoring was running
        # on time over thousands of traders.
        scoring_minutes_ago = 9999
        if last_scoring_at:
            scoring_minutes_ago = (
                datetime.now(timezone.utc) - datetime.fromisoformat(last_scoring_at)
            ).total_seconds() / 60

        if traders_scored <= 0:
            status = 'unhealthy'
        elif scoring_minutes_ago < 120:
            status = 'healthy'
        else:
            status = 'degraded'

        # Drift needs a baseline to be measured against, and there is none:
        # aware_ml_drift_reports is empty because the job that fills it never
        # runs. Saying so beats deriving a number from how old another table is.
        drift_status = 'unavailable'
        drift_ratio = 0.0
        drifted_features = []

        return {
            'status': status,
            'model_version': model_version,
            'last_scoring_at': last_scoring_at,
            'traders_scored': traders_scored,
            'scoring_method': scoring_method,
            'tier_distribution': tier_distribution,
            'drift_status': drift_status,
            'drift_ratio': drift_ratio,
            'drifted_features': drifted_features,
            # Null rather than a staleness figure when nothing has ever
            # produced enrichment, so the page can say so plainly.
            'enrichment_minutes_ago': enrichment_minutes_ago,
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get ML health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# FUND MANAGEMENT ENDPOINTS (Proxy to Java strategy-service)
# ============================================================================

import requests as http_requests

STRATEGY_SERVICE_URL = os.getenv('STRATEGY_SERVICE_URL', 'http://localhost:8081')


class FundStatus(BaseModel):
    """Fund operational status from Java service."""
    fund_id: str
    fund_type: str
    is_active: bool
    capital_usd: float
    position_count: int
    pending_signals: int
    last_trade_at: Optional[UtcDatetime]
    daily_trades: int
    daily_notional_usd: float
    error_message: Optional[str]


class FundActivateRequest(BaseModel):
    """Request to activate a fund."""
    fund_type: str
    capital_usd: float = 10000.0


class FundActivateResponse(BaseModel):
    """Response after activating a fund."""
    success: bool
    fund_type: str
    message: str




# Not exposed: this dashboard is read-only and reachable without
# credentials. Controlling funds over an unauthenticated public
# endpoint has no upside here. Re-enable behind auth if ever needed.
# @app.post("/api/fund/activate")
async def activate_fund(request: FundActivateRequest):
    """
    Activate a fund in the Java strategy service.

    This starts the fund's trading logic (paper trading by default).
    """
    try:
        response = http_requests.post(
            f"{STRATEGY_SERVICE_URL}/api/strategy/fund/activate",
            json={
                'fundType': request.fund_type,
                'capitalUsd': request.capital_usd
            },
            timeout=10
        )

        if response.ok:
            data = response.json()
            return FundActivateResponse(
                success=True,
                fund_type=request.fund_type,
                message=data.get('message', 'Fund activated successfully')
            )

        return FundActivateResponse(
            success=False,
            fund_type=request.fund_type,
            message=f"Strategy service returned: {response.status_code}"
        )

    except http_requests.exceptions.RequestException as e:
        return FundActivateResponse(
            success=False,
            fund_type=request.fund_type,
            message=f"Strategy service unavailable: {str(e)}"
        )
    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to activate fund: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Not exposed: this dashboard is read-only and reachable without
# credentials. Controlling funds over an unauthenticated public
# endpoint has no upside here. Re-enable behind auth if ever needed.
# @app.post("/api/fund/pause")
async def pause_fund(fund_type: str = Query(...)):
    """
    Pause trading for a fund.

    The fund will stop taking new positions but will manage existing ones.
    """
    try:
        response = http_requests.post(
            f"{STRATEGY_SERVICE_URL}/api/strategy/fund/pause",
            params={'fundType': fund_type},
            timeout=10
        )

        if response.ok:
            return {
                'success': True,
                'fund_type': fund_type,
                'message': 'Fund paused successfully'
            }

        return {
            'success': False,
            'fund_type': fund_type,
            'message': f"Strategy service returned: {response.status_code}"
        }

    except http_requests.exceptions.RequestException as e:
        return {
            'success': False,
            'fund_type': fund_type,
            'message': f"Strategy service unavailable: {str(e)}"
        }
    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to pause fund: {e}")
        raise HTTPException(status_code=500, detail=str(e))






# ============================================================================
# ML MODEL ENDPOINTS
# ============================================================================


class TraderEnrichmentFull(BaseModel):
    """Extended trader enrichment with ML scores."""
    proxy_address: str
    username: str
    # ML Enrichment
    cluster_id: int
    strategy_cluster: str
    cluster_description: str
    is_anomaly: bool
    anomaly_score: float
    anomaly_type: str
    # ML Scores
    ml_score: float
    ml_tier: str
    tier_confidence: float
    predicted_sharpe: float
    sharpe_lower: Optional[float] = None
    sharpe_upper: Optional[float] = None
    # Profile
    total_volume: float
    total_pnl: float
    updated_at: Optional[UtcDatetime] = None


class FeatureImportance(BaseModel):
    """Feature importance entry."""
    name: str
    importance: float
    rank: int


class TierBoundary(BaseModel):
    """Tier boundary definition."""
    tier: str
    min_score: float
    max_score: float
    description: str


class ModelInfo(BaseModel):
    """ML model metadata."""
    model_version: str
    trained_at: Optional[UtcDatetime] = None
    n_traders_trained: int
    tier_accuracy: float
    sharpe_mae: float
    top_features: list[dict]
    tier_boundaries: list[dict]


class DriftedFeature(BaseModel):
    """Drifted feature info."""
    name: str
    severity: str
    ks_stat: float


class DriftStatus(BaseModel):
    """Current drift monitoring status."""
    status: str
    drift_ratio: float
    n_drifted_features: int
    n_total_features: int
    drifted_features: list[dict]
    last_checked: Optional[UtcDatetime] = None
    baseline_date: Optional[str] = None
    retrain_recommended: bool


@app.get("/api/traders/{address}/enrichment", response_model=TraderEnrichmentFull)
@limiter.limit("60/minute")
async def get_trader_enrichment_full(request: Request, address: str):
    """
    Get complete ML enrichment for a trader.

    Includes clustering, anomaly detection, and ML scores.
    """
    try:
        client = get_clickhouse_client()

        result = client.query("""
            SELECT
                ml.proxy_address, ml.username,
                ml.cluster_id, ml.strategy_cluster, ml.cluster_description,
                ml.is_anomaly, ml.anomaly_score, ml.anomaly_type,
                s.ml_score, s.ml_tier, s.tier_confidence,
                s.predicted_sharpe_30d,
                p.total_volume_usd, p.total_pnl,
                ml.updated_at
            FROM (SELECT * FROM polybot.aware_ml_enrichment FINAL) AS ml
            LEFT JOIN (SELECT * FROM polybot.aware_ml_scores FINAL) AS s
                ON ml.proxy_address = s.proxy_address
            LEFT JOIN (SELECT * FROM polybot.aware_trader_profiles FINAL) AS p
                ON ml.proxy_address = p.proxy_address
            WHERE lower(ml.proxy_address) = lower(%(addr)s)
               OR lower(ml.username) = lower(%(addr)s)
            LIMIT 1
        """, parameters={'addr': address})

        if not result.result_rows:
            raise HTTPException(404, "Trader enrichment not found")

        row = result.result_rows[0]
        return TraderEnrichmentFull(
            proxy_address=row[0],
            username=row[1] or '',
            cluster_id=int(row[2]) if row[2] is not None else 0,
            strategy_cluster=row[3] or 'UNKNOWN',
            cluster_description=row[4] or '',
            is_anomaly=bool(row[5]) if row[5] is not None else False,
            anomaly_score=float(row[6]) if row[6] else 0.0,
            anomaly_type=row[7] or '',
            ml_score=float(row[8]) if row[8] else 0.0,
            ml_tier=row[9] or 'UNKNOWN',
            tier_confidence=float(row[10]) if row[10] else 0.0,
            predicted_sharpe=float(row[11]) if row[11] else 0.0,
            total_volume=float(row[12]) if row[12] else 0.0,
            total_pnl=float(row[13]) if row[13] else 0.0,
            updated_at=row[14]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get trader enrichment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/models/ensemble/info", response_model=ModelInfo)
@limiter.limit("30/minute")
async def get_model_info(request: Request):
    """
    Get current ML model metadata and feature importance.

    Returns model version, training date, accuracy metrics, and top features.
    """
    try:
        client = get_clickhouse_client()

        # Get latest training run
        training_result = client.query("""
            SELECT model_version, completed_at, n_traders,
                   tier_accuracy, sharpe_mae
            FROM polybot.aware_ml_training_runs
            WHERE status = 'success'
            ORDER BY completed_at DESC
            LIMIT 1
        """)

        # Get feature importance
        importance_result = client.query("""
            SELECT feature_name, importance_score, importance_rank
            FROM polybot.aware_ml_feature_importance FINAL
            ORDER BY importance_rank
            LIMIT 15
        """)

        # Get tier boundaries
        tier_result = client.query("""
            SELECT tier_name, score_min, score_max, description
            FROM polybot.aware_ml_tier_boundaries FINAL
            ORDER BY score_min
        """)

        training = training_result.result_rows[0] if training_result.result_rows else None

        return ModelInfo(
            model_version=training[0] if training else 'unknown',
            trained_at=training[1] if training else None,
            n_traders_trained=int(training[2]) if training and training[2] else 0,
            tier_accuracy=float(training[3]) if training and training[3] else 0.0,
            sharpe_mae=float(training[4]) if training and training[4] else 0.0,
            top_features=[
                {'name': r[0], 'importance': float(r[1]), 'rank': int(r[2])}
                for r in importance_result.result_rows
            ],
            tier_boundaries=[
                {'tier': r[0], 'min': float(r[1]), 'max': float(r[2]), 'desc': r[3]}
                for r in tier_result.result_rows
            ]
        )

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get model info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/models/drift-status", response_model=DriftStatus)
@limiter.limit("30/minute")
async def get_drift_status(request: Request):
    """
    Get current drift monitoring status.

    Shows if model features are drifting from training distribution
    and whether retraining is recommended.
    """
    try:
        import json
        from pathlib import Path

        # Load latest drift report from file
        # Check multiple locations (Docker mount vs local dev)
        possible_paths = [
            Path("/app/ml/checkpoints/latest_drift_report.json"),  # Docker
            Path(__file__).parent.parent / "analytics" / "ml" / "checkpoints" / "latest_drift_report.json",  # Local dev
            Path("ml/checkpoints/latest_drift_report.json"),  # Relative
        ]
        drift_path = None
        for p in possible_paths:
            if p.exists():
                drift_path = p
                break

        if drift_path is None:
            return DriftStatus(
                status='unknown',
                drift_ratio=0.0,
                n_drifted_features=0,
                n_total_features=35,
                drifted_features=[],
                last_checked=None,
                baseline_date=None,
                retrain_recommended=False
            )

        with open(drift_path) as f:
            report = json.load(f)

        return DriftStatus(
            status=report.get('alert_level', 'unknown'),
            drift_ratio=report.get('drift_ratio', 0.0),
            n_drifted_features=report.get('n_drifted', 0),
            n_total_features=report.get('n_features', 35),
            drifted_features=[
                {'name': f['feature'], 'severity': f['severity'], 'ks_stat': f['ks_statistic']}
                for f in report.get('drifted_features', [])
            ],
            last_checked=datetime.fromisoformat(report['checked_at']) if 'checked_at' in report else None,
            baseline_date=report.get('baseline_date'),
            retrain_recommended=report.get('drift_ratio', 0) >= 0.3
        )

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get drift status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/models/training-history")
@limiter.limit("30/minute")
async def get_training_history(
    request: Request,
    limit: int = Query(default=10, ge=1, le=50)
):
    """
    Get recent model training runs.

    Shows history of training runs with metrics and status.
    """
    try:
        client = get_clickhouse_client()

        result = client.query(f"""
            SELECT
                toString(run_id) as run_id,
                model_version,
                started_at,
                completed_at,
                duration_seconds,
                status,
                n_traders,
                tier_accuracy,
                sharpe_mae,
                trigger_reason
            FROM polybot.aware_ml_training_runs
            ORDER BY started_at DESC
            LIMIT {limit}
        """)

        return {
            'count': len(result.result_rows),
            'runs': [
                {
                    'run_id': row[0],
                    'model_version': row[1],
                    'started_at': utc_iso(row[2]) if row[2] else None,
                    'completed_at': utc_iso(row[3]) if row[3] else None,
                    'duration_seconds': int(row[4]) if row[4] else 0,
                    'status': row[5],
                    'n_traders': int(row[6]) if row[6] else 0,
                    'tier_accuracy': float(row[7]) if row[7] else 0.0,
                    'sharpe_mae': float(row[8]) if row[8] else 0.0,
                    'trigger_reason': row[9]
                }
                for row in result.result_rows
            ]
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get training history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/models/feature-importance")
@limiter.limit("30/minute")
async def get_feature_importance(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    importance_type: str = Query(default="weight")
):
    """
    Get feature importance rankings from the ML model.

    Returns top features ranked by importance score.
    """
    try:
        client = get_clickhouse_client()

        result = client.query(f"""
            SELECT
                feature_name,
                importance_score,
                importance_rank,
                model_version,
                importance_type
            FROM polybot.aware_ml_feature_importance FINAL
            WHERE importance_type = %(imp_type)s
            ORDER BY importance_rank
            LIMIT {limit}
        """, parameters={'imp_type': importance_type})

        return {
            'importance_type': importance_type,
            'count': len(result.result_rows),
            'features': [
                {
                    'rank': int(row[2]),
                    'name': row[0],
                    'importance': float(row[1]),
                    'model_version': row[3]
                }
                for row in result.result_rows
            ]
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get feature importance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ml/tier-distribution")
@limiter.limit("60/minute")
async def get_tier_distribution(request: Request):
    """
    Get distribution of traders across ML tiers.

    Shows how many traders are in each tier (BRONZE, SILVER, GOLD, DIAMOND).
    """
    try:
        client = get_clickhouse_client()

        result = client.query("""
            SELECT
                ml_tier,
                count() as trader_count,
                avg(ml_score) as avg_score,
                avg(predicted_sharpe_30d) as avg_sharpe
            FROM polybot.aware_ml_scores FINAL
            WHERE ml_tier != ''
            GROUP BY ml_tier
            ORDER BY
                CASE ml_tier
                    WHEN 'DIAMOND' THEN 1
                    WHEN 'GOLD' THEN 2
                    WHEN 'SILVER' THEN 3
                    WHEN 'BRONZE' THEN 4
                    ELSE 5
                END
        """)

        tiers = []
        total = 0
        for row in result.result_rows:
            count = int(row[1])
            total += count
            tiers.append({
                'tier': row[0],
                'count': count,
                'avg_score': round(float(row[2]) if row[2] else 0, 2),
                'avg_sharpe': round(float(row[3]) if row[3] else 0, 3)
            })

        # Add percentages
        for tier in tiers:
            tier['percentage'] = round(tier['count'] / total * 100, 1) if total > 0 else 0

        return {
            'total_traders': total,
            'tiers': tiers
        }

    except HTTPException:
        # A deliberate 4xx must keep its status; the generic handler below
        # would otherwise turn every validation error into a 500.
        raise
    except Exception as e:
        logger.error(f"Failed to get tier distribution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Entry point"""
    host = os.getenv('API_HOST', '0.0.0.0')
    port = int(os.getenv('API_PORT', '8000'))

    logger.info("=" * 60)
    logger.info("  AWARE API - Starting")
    logger.info("=" * 60)
    logger.info(f"  Host: {host}:{port}")
    logger.info("=" * 60)

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
