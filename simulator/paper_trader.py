import psycopg2
from decimal import Decimal


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
# CAPITAL
# -------------------------------------------------------------------

def get_current_capital(cur):
    """
    Devuelve el último capital_after disponible.
    Si todavía no hay trades cerrados, usa el capital inicial ficticio.
    """
    cur.execute("""
        SELECT capital_after
        FROM simulated_trades
        WHERE strategy_name = %s
          AND capital_after IS NOT NULL
        ORDER BY closed_at DESC NULLS LAST, created_at DESC
        LIMIT 1;
    """, (STRATEGY_NAME,))

    row = cur.fetchone()

    if row and row[0] is not None:
        return Decimal(row[0])

    return INITIAL_CAPITAL


# -------------------------------------------------------------------
# CONTROL DE TRADES ABIERTOS
# -------------------------------------------------------------------

def count_open_trades(cur):
    """
    Cuenta trades abiertos para respetar el límite de operaciones simultáneas.
    """
    cur.execute("""
        SELECT COUNT(*)
        FROM simulated_trades
        WHERE strategy_name = %s
          AND status = 'open';
    """, (STRATEGY_NAME,))

    return cur.fetchone()[0]


# -------------------------------------------------------------------
# TRAER SEÑALES NUEVAS
# -------------------------------------------------------------------

def get_open_signals_without_trade(cur):
    """
    Trae señales abiertas que todavía no tengan trade simulado asociado.
    """
    cur.execute("""
        SELECT
            s.id,
            s.experiment_run_id,
            s.token_id,
            s.symbol,
            s.signal_level,
            s.price_at_signal,
            s.realistic_entry_price,
            s.stop_price,
            s.tp1_price,
            s.tp2_price,
            s.tp3_price,
            s.allocation_pct
        FROM signals s
        LEFT JOIN simulated_trades t
            ON t.signal_id = s.id
        WHERE s.status = 'open'
          AND t.id IS NULL
        ORDER BY 
            CASE 
                WHEN s.signal_level = 'high' THEN 1
                WHEN s.signal_level = 'medium' THEN 2
                ELSE 3
            END,
            s.created_at ASC;
    """)

    return cur.fetchall()


# -------------------------------------------------------------------
# ABRIR TRADE
# -------------------------------------------------------------------

def open_simulated_trade(cur, signal, capital_before):
    (
        signal_id,
        experiment_run_id,
        token_id,
        symbol,
        signal_level,
        price_at_signal,
        realistic_entry_price,
        stop_price,
        tp1_price,
        tp2_price,
        tp3_price,
        allocation_pct,
    ) = signal

    entry_price = Decimal(realistic_entry_price or price_at_signal)

    if entry_price <= 0:
        print(f"[SKIP] {symbol} precio inválido: {entry_price}")
        return None

    allocation = Decimal(allocation_pct) / Decimal("100")
    allocated_capital = capital_before * allocation

    if allocated_capital <= 0:
        print(f"[SKIP] {symbol} capital asignado inválido: {allocated_capital}")
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
        capital_before,
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
                'allocated_capital', %s,
                'entry_price', %s,
                'quantity', %s,
                'allocation_pct', %s
            )
        );
    """, (
        experiment_run_id,
        trade_id,
        symbol,
        f"Opened simulated trade for {symbol}",
        signal_level,
        str(capital_before),
        str(allocated_capital),
        str(entry_price),
        str(quantity),
        str(allocation_pct),
    ))

    # Marcar señal como ejecutada para no duplicar trades.
    # El trade queda abierto; la señal solo queda consumida.
    cur.execute("""
        UPDATE signals
        SET status = 'executed'
        WHERE id = %s;
    """, (signal_id,))

    return trade_id, allocated_capital, quantity, entry_price


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------

def main():
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn:
            with conn.cursor() as cur:
                signals = get_open_signals_without_trade(cur)

                if not signals:
                    print("No hay señales abiertas sin trade simulado.")
                    return

                open_trades = count_open_trades(cur)

                print(f"Señales nuevas: {len(signals)}")
                print(f"Trades abiertos actuales: {open_trades}")

                for signal in signals:
                    if open_trades >= MAX_OPEN_TRADES:
                        print(f"Máximo de trades abiertos alcanzado ({MAX_OPEN_TRADES}).")
                        break

                    capital_before = get_current_capital(cur)

                    result = open_simulated_trade(
                        cur,
                        signal,
                        capital_before
                    )

                    if not result:
                        continue

                    trade_id, allocated_capital, quantity, entry_price = result
                    open_trades += 1

                    print("-" * 80)
                    print(f"[TRADE OPEN] {trade_id}")
                    print(f"Capital antes: {capital_before}")
                    print(f"Capital asignado: {allocated_capital}")
                    print(f"Precio entrada: {entry_price}")
                    print(f"Cantidad: {quantity}")

        print("\nProceso terminado.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()