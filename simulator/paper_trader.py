import sys
from pathlib import Path
from decimal import Decimal

import psycopg2


# Permite importar desde /strategies aunque este archivo esté en /simulator
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from strategies.signal_ranker import score_signal  # noqa: E402


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}

INITIAL_CAPITAL = Decimal("200")
STRATEGY_NAME = "alpha_momentum_v0"
MAX_OPEN_TRADES = 2


# -------------------------------------------------------------------
# HELPERS
# -------------------------------------------------------------------

def to_decimal(value, default="0"):
    if value is None:
        return Decimal(default)

    if isinstance(value, Decimal):
        return value

    return Decimal(str(value))


# -------------------------------------------------------------------
# CAPITAL
# -------------------------------------------------------------------

def get_realized_capital(cur):
    """
    Calcula capital global correcto:

    capital inicial + suma de P/L de todos los trades cerrados.

    Esto corrige el problema de leer capital_after desde una sola fila,
    que no sirve cuando hubo trades simultáneos.
    """
    cur.execute("""
        SELECT
            COALESCE(
                SUM(
                    allocated_capital * (net_return_pct / 100)
                ),
                0
            ) AS realized_pnl
        FROM simulated_trades
        WHERE strategy_name = %s
          AND status = 'closed'
          AND net_return_pct IS NOT NULL;
    """, (STRATEGY_NAME,))

    realized_pnl = to_decimal(cur.fetchone()[0])
    return INITIAL_CAPITAL + realized_pnl


def get_open_allocated_capital(cur):
    """
    Capital actualmente comprometido en trades abiertos.
    """
    cur.execute("""
        SELECT COALESCE(SUM(allocated_capital), 0)
        FROM simulated_trades
        WHERE strategy_name = %s
          AND status = 'open';
    """, (STRATEGY_NAME,))

    return to_decimal(cur.fetchone()[0])


def get_available_capital(cur):
    realized_capital = get_realized_capital(cur)
    open_allocated = get_open_allocated_capital(cur)

    available = realized_capital - open_allocated

    if available < 0:
        return Decimal("0")

    return available


# -------------------------------------------------------------------
# CONTROL DE TRADES ABIERTOS
# -------------------------------------------------------------------

def count_open_trades(cur):
    cur.execute("""
        SELECT COUNT(*)
        FROM simulated_trades
        WHERE strategy_name = %s
          AND status = 'open';
    """, (STRATEGY_NAME,))

    return cur.fetchone()[0]


def get_open_trade_symbols(cur):
    cur.execute("""
        SELECT DISTINCT symbol
        FROM simulated_trades
        WHERE strategy_name = %s
          AND status = 'open';
    """, (STRATEGY_NAME,))

    return {row[0] for row in cur.fetchall()}


# -------------------------------------------------------------------
# TRAER SEÑALES ABIERTAS CON FEATURES
# -------------------------------------------------------------------

def get_open_signals_without_trade(cur):
    """
    Trae señales abiertas que todavía no tengan trade asociado,
    junto con sus features para poder calcular ranking_score.
    """
    cur.execute("""
        SELECT
            s.id AS signal_id,
            s.experiment_run_id,
            s.token_id,
            s.feature_id,
            s.symbol,
            s.signal_level,
            s.price_at_signal,
            s.realistic_entry_price,
            s.stop_price,
            s.tp1_price,
            s.tp2_price,
            s.tp3_price,
            s.allocation_pct,
            s.created_at,

            f.price_change_15m_pct,
            f.price_change_1h_pct,
            f.price_change_24h_pct,
            f.relative_volume_15m,
            f.relative_volume_1h,
            f.spread_pct,
            f.liquidity_gate_passed
        FROM signals s
        LEFT JOIN features f
            ON f.id = s.feature_id
        LEFT JOIN simulated_trades t
            ON t.signal_id = s.id
        WHERE s.status = 'open'
          AND t.id IS NULL
        ORDER BY s.created_at ASC;
    """)

    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()

    return [dict(zip(columns, row)) for row in rows]


# -------------------------------------------------------------------
# RANKING Y DEDUP
# -------------------------------------------------------------------

def rank_and_deduplicate_signals(signals, open_trade_symbols):
    """
    Ordena señales por ranking_score y deja solo la mejor señal por símbolo.

    También excluye símbolos que ya tienen trade abierto.
    """
    ranked = []

    for signal in signals:
        if signal["symbol"] in open_trade_symbols:
            continue

        signal["ranking_score"] = score_signal(signal)
        ranked.append(signal)

    ranked.sort(
        key=lambda item: (
            item.get("ranking_score", 0),
            1 if item.get("signal_level") == "high" else 0,
            item.get("created_at"),
        ),
        reverse=True,
    )

    best_by_symbol = {}
    superseded_signal_ids = []

    for signal in ranked:
        symbol = signal["symbol"]

        if symbol not in best_by_symbol:
            best_by_symbol[symbol] = signal
        else:
            superseded_signal_ids.append(signal["signal_id"])

    selected = list(best_by_symbol.values())

    selected.sort(
        key=lambda item: (
            item.get("ranking_score", 0),
            1 if item.get("signal_level") == "high" else 0,
        ),
        reverse=True,
    )

    return selected, superseded_signal_ids


def mark_superseded_signals(cur, signal_ids):
    if not signal_ids:
        return

    signal_ids_as_text = [str(signal_id) for signal_id in signal_ids]

    cur.execute("""
        UPDATE signals
        SET status = 'superseded'
        WHERE id::text = ANY(%s);
    """, (signal_ids_as_text,))


# -------------------------------------------------------------------
# ABRIR TRADE
# -------------------------------------------------------------------

def open_simulated_trade(cur, signal, realized_capital, available_capital):
    signal_id = signal["signal_id"]
    experiment_run_id = signal["experiment_run_id"]
    token_id = signal["token_id"]
    symbol = signal["symbol"]
    signal_level = signal["signal_level"]
    price_at_signal = signal["price_at_signal"]
    realistic_entry_price = signal["realistic_entry_price"]
    stop_price = signal["stop_price"]
    tp1_price = signal["tp1_price"]
    tp2_price = signal["tp2_price"]
    tp3_price = signal["tp3_price"]
    allocation_pct = signal["allocation_pct"]
    ranking_score = signal.get("ranking_score", 0)

    entry_price = to_decimal(realistic_entry_price or price_at_signal)

    if entry_price <= 0:
        print(f"[SKIP] {symbol} precio inválido: {entry_price}")
        return None

    allocation = to_decimal(allocation_pct) / Decimal("100")
    allocated_capital = realized_capital * allocation

    if allocated_capital <= 0:
        print(f"[SKIP] {symbol} capital asignado inválido: {allocated_capital}")
        return None

    if allocated_capital > available_capital:
        print(
            f"[SKIP] {symbol} capital insuficiente. "
            f"Necesita={allocated_capital}, disponible={available_capital}"
        )
        return None

    quantity = allocated_capital / entry_price

    cur.execute("""
        INSERT INTO simulated_trades (
            experiment_run_id,
            signal_id,
            token_id,
            symbol,
            strategy_name,
            is_benchmark,
            status,
            capital_before,
            allocated_capital,
            quantity,
            entry_price_ideal,
            entry_price_realistic,
            stop_price,
            tp1_price,
            tp2_price,
            tp3_price,
            opened_at
        )
        VALUES (
            %s, %s, %s, %s,
            %s, FALSE, 'open',
            %s, %s, %s,
            %s, %s,
            %s, %s, %s, %s,
            NOW()
        )
        RETURNING id;
    """, (
        experiment_run_id,
        signal_id,
        token_id,
        symbol,
        STRATEGY_NAME,
        realized_capital,
        allocated_capital,
        quantity,
        price_at_signal,
        entry_price,
        stop_price,
        tp1_price,
        tp2_price,
        tp3_price,
    ))

    trade_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO trade_logs (
            experiment_run_id,
            trade_id,
            symbol,
            action,
            message,
            payload
        )
        VALUES (
            %s, %s, %s,
            'OPEN',
            %s,
            jsonb_build_object(
                'signal_level', %s,
                'capital_before', %s,
                'available_capital_before', %s,
                'allocated_capital', %s,
                'entry_price', %s,
                'quantity', %s,
                'allocation_pct', %s,
                'ranking_score', %s
            )
        );
    """, (
        experiment_run_id,
        trade_id,
        symbol,
        f"Opened simulated trade for {symbol}",
        signal_level,
        str(realized_capital),
        str(available_capital),
        str(allocated_capital),
        str(entry_price),
        str(quantity),
        str(allocation_pct),
        str(ranking_score),
    ))

    cur.execute("""
        UPDATE signals
        SET status = 'executed'
        WHERE id = %s;
    """, (signal_id,))

    # Evita que señales viejas del mismo símbolo se ejecuten después.
    cur.execute("""
        UPDATE signals
        SET status = 'superseded'
        WHERE symbol = %s
          AND status = 'open'
          AND id <> %s;
    """, (symbol, signal_id))

    return trade_id, allocated_capital, quantity, entry_price, ranking_score


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------

def main():
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn:
            with conn.cursor() as cur:
                open_trades = count_open_trades(cur)
                open_trade_symbols = get_open_trade_symbols(cur)

                realized_capital = get_realized_capital(cur)
                available_capital = get_available_capital(cur)

                signals = get_open_signals_without_trade(cur)
                ranked_signals, superseded_ids = rank_and_deduplicate_signals(
                    signals,
                    open_trade_symbols
                )

                mark_superseded_signals(cur, superseded_ids)

                print(f"Capital realizado: {realized_capital}")
                print(f"Capital disponible: {available_capital}")
                print(f"Trades abiertos actuales: {open_trades}")
                print(f"Señales open encontradas: {len(signals)}")
                print(f"Señales rankeadas/deduplicadas: {len(ranked_signals)}")

                if not ranked_signals:
                    print("No hay señales abiertas disponibles para abrir trade.")
                    return

                for signal in ranked_signals:
                    if open_trades >= MAX_OPEN_TRADES:
                        print(f"Máximo de trades abiertos alcanzado ({MAX_OPEN_TRADES}).")
                        break

                    available_capital = get_available_capital(cur)

                    result = open_simulated_trade(
                        cur,
                        signal,
                        realized_capital,
                        available_capital
                    )

                    if not result:
                        continue

                    trade_id, allocated_capital, quantity, entry_price, ranking_score = result
                    open_trades += 1

                    print("-" * 100)
                    print(f"[TRADE OPEN] {trade_id}")
                    print(f"Symbol: {signal['symbol']}")
                    print(f"Level: {signal['signal_level']}")
                    print(f"Ranking score: {ranking_score}")
                    print(f"Capital base: {realized_capital}")
                    print(f"Capital asignado: {allocated_capital}")
                    print(f"Precio entrada: {entry_price}")
                    print(f"Cantidad: {quantity}")

        print("\nProceso terminado.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()