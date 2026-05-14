CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Alpha Momentum Predictor
-- Schema v0.2 (Definitiva)

CREATE TABLE IF NOT EXISTS experiment_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    initial_capital_usdt NUMERIC(18,8) NOT NULL,
    current_capital_usdt NUMERIC(18,8),
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alpha_token_id TEXT,
    symbol TEXT NOT NULL UNIQUE,
    name TEXT,
    source TEXT NOT NULL DEFAULT 'binance_alpha',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    raw_payload JSONB,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw_tickers_24h (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_id UUID REFERENCES raw_tokens(id),
    symbol TEXT NOT NULL,
    price NUMERIC(30,12),
    price_change_pct NUMERIC(18,8),
    high_price NUMERIC(30,12),
    low_price NUMERIC(30,12),
    volume NUMERIC(30,12),
    quote_volume NUMERIC(30,12),
    raw_payload JSONB,
    exchange_time TIMESTAMPTZ,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw_candles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_id UUID REFERENCES raw_tokens(id),
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    open_time TIMESTAMPTZ NOT NULL,
    close_time TIMESTAMPTZ NOT NULL,
    open_price NUMERIC(30,12) NOT NULL,
    high_price NUMERIC(30,12) NOT NULL,
    low_price NUMERIC(30,12) NOT NULL,
    close_price NUMERIC(30,12) NOT NULL,
    volume NUMERIC(30,12),
    quote_volume NUMERIC(30,12),
    raw_payload JSONB,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(symbol, interval, open_time)
);

CREATE TABLE IF NOT EXISTS raw_order_book_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_id UUID REFERENCES raw_tokens(id),
    symbol TEXT NOT NULL,
    depth_limit INTEGER NOT NULL,
    best_bid NUMERIC(30,12),
    best_ask NUMERIC(30,12),
    mid_price NUMERIC(30,12),
    spread_pct NUMERIC(18,8),
    total_bid_liquidity NUMERIC(30,12),
    total_ask_liquidity NUMERIC(30,12),
    bids JSONB,
    asks JSONB,
    raw_payload JSONB,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS features (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_run_id UUID REFERENCES experiment_runs(id),
    token_id UUID REFERENCES raw_tokens(id),
    symbol TEXT NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    price_change_15m_pct NUMERIC(18,8),
    price_change_1h_pct NUMERIC(18,8),
    price_change_24h_pct NUMERIC(18,8),

    relative_volume_15m NUMERIC(18,8),
    relative_volume_1h NUMERIC(18,8),

    distance_to_24h_high_pct NUMERIC(18,8),
    distance_to_24h_low_pct NUMERIC(18,8),

    spread_pct NUMERIC(18,8),
    estimated_slippage_pct NUMERIC(18,8),

    liquidity_gate_passed BOOLEAN,
    momentum_15m_positive BOOLEAN,
    momentum_1h_positive BOOLEAN,
    momentum_1h_recovering BOOLEAN,
    strong_drop_active BOOLEAN,
    extreme_pump_recent BOOLEAN
);

CREATE TABLE IF NOT EXISTS signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_run_id UUID REFERENCES experiment_runs(id),
    token_id UUID REFERENCES raw_tokens(id),
    feature_id UUID REFERENCES features(id),
    symbol TEXT NOT NULL,
    signal_level TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',

    price_at_signal NUMERIC(30,12),
    realistic_entry_price NUMERIC(30,12),

    stop_price NUMERIC(30,12),
    tp1_price NUMERIC(30,12),
    tp2_price NUMERIC(30,12),
    tp3_price NUMERIC(30,12),

    allocation_pct NUMERIC(10,4),
    reason JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS simulated_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_run_id UUID REFERENCES experiment_runs(id),
    signal_id UUID REFERENCES signals(id),
    token_id UUID REFERENCES raw_tokens(id),
    symbol TEXT NOT NULL,

    strategy_name TEXT NOT NULL,
    is_benchmark BOOLEAN NOT NULL DEFAULT FALSE,

    status TEXT NOT NULL DEFAULT 'open',

    capital_before NUMERIC(18,8),
    allocated_capital NUMERIC(18,8),
    quantity NUMERIC(30,12),

    entry_price_ideal NUMERIC(30,12),
    entry_price_realistic NUMERIC(30,12),

    exit_price_ideal NUMERIC(30,12),
    exit_price_realistic NUMERIC(30,12),

    stop_price NUMERIC(30,12),
    tp1_price NUMERIC(30,12),
    tp2_price NUMERIC(30,12),
    tp3_price NUMERIC(30,12),

    gross_return_pct NUMERIC(18,8),
    fees_pct NUMERIC(18,8),
    slippage_pct NUMERIC(18,8),
    net_return_pct NUMERIC(18,8),

    capital_after NUMERIC(18,8),
    exit_reason TEXT,

    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS performance_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_run_id UUID REFERENCES experiment_runs(id),
    strategy_name TEXT NOT NULL,

    report_start TIMESTAMPTZ,
    report_end TIMESTAMPTZ,

    capital_initial NUMERIC(18,8),
    capital_final NUMERIC(18,8),
    multiplier NUMERIC(18,8),

    win_rate NUMERIC(18,8),
    avg_win NUMERIC(18,8),
    avg_loss NUMERIC(18,8),
    expected_value NUMERIC(18,8),
    profit_factor NUMERIC(18,8),
    max_drawdown_pct NUMERIC(18,8),

    tp1_hit_rate NUMERIC(18,8),
    tp2_hit_rate NUMERIC(18,8),
    tp3_hit_rate NUMERIC(18,8),
    stop_hit_rate NUMERIC(18,8),

    average_slippage_pct NUMERIC(18,8),

    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_run_id UUID REFERENCES experiment_runs(id),

    event_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id UUID,
    symbol TEXT,

    message TEXT,
    payload JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS collector_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    collector_name TEXT NOT NULL,
    status TEXT NOT NULL,
    symbol TEXT,

    message TEXT,
    payload JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS signal_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_run_id UUID REFERENCES experiment_runs(id),
    signal_id UUID REFERENCES signals(id),

    symbol TEXT,
    action TEXT NOT NULL,

    message TEXT,
    payload JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trade_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_run_id UUID REFERENCES experiment_runs(id),
    trade_id UUID REFERENCES simulated_trades(id),

    symbol TEXT,
    action TEXT NOT NULL,

    message TEXT,
    payload JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS error_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    source TEXT NOT NULL,
    symbol TEXT,
    error_type TEXT,

    message TEXT,
    payload JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices optimizados

CREATE INDEX IF NOT EXISTS idx_tickers_token_id 
ON raw_tickers_24h(token_id);

CREATE INDEX IF NOT EXISTS idx_raw_tickers_symbol_collected 
ON raw_tickers_24h(symbol, collected_at);

CREATE INDEX IF NOT EXISTS idx_raw_candles_token_id 
ON raw_candles(token_id);

CREATE INDEX IF NOT EXISTS idx_order_book_token_id 
ON raw_order_book_snapshots(token_id);

CREATE INDEX IF NOT EXISTS idx_order_book_symbol_collected 
ON raw_order_book_snapshots(symbol, collected_at);

CREATE INDEX IF NOT EXISTS idx_features_symbol_calculated 
ON features(symbol, calculated_at);

CREATE INDEX IF NOT EXISTS idx_signals_symbol_created 
ON signals(symbol, created_at);

CREATE INDEX IF NOT EXISTS idx_trades_strategy_status 
ON simulated_trades(strategy_name, status);

CREATE INDEX IF NOT EXISTS idx_trades_symbol_status 
ON simulated_trades(symbol, status);

CREATE INDEX IF NOT EXISTS idx_audit_events_created 
ON audit_events(created_at);

CREATE INDEX IF NOT EXISTS idx_collector_logs_created 
ON collector_logs(created_at);

CREATE INDEX IF NOT EXISTS idx_error_logs_created 
ON error_logs(created_at);

CREATE OR REPLACE VIEW v_tradeable_tokens AS
SELECT
    tradeable.id AS tradeable_token_id,
    tradeable.symbol AS trading_symbol,
    tradeable.alpha_token_id,
    visible.symbol AS display_symbol,
    visible.name AS display_name,
    tradeable.raw_payload AS tradeable_payload,
    visible.raw_payload AS visible_payload,
    tradeable.last_seen_at
FROM raw_tokens tradeable
LEFT JOIN raw_tokens visible
    ON visible.alpha_token_id = tradeable.alpha_token_id
    AND visible.symbol NOT LIKE 'ALPHA_%USDT'
WHERE tradeable.symbol LIKE 'ALPHA_%USDT';