import psycopg2
from decimal import Decimal
from datetime import datetime, timezone


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}

STRATEGY_NAME = "alpha_momentum_v0"
ENTRY_FEE_PCT = Decimal("0.1")
EXIT_FEE_PCT = Decimal("0.1")


# -------------------------------------------------------------------
# TRADES ABIERTOS
# -------------------------------------------------------------------

def get_open_trades(cur):
    cur.execute("""
        SELECT
            id,
            experiment_run_id,
            token_id,
            symbol,
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
        FROM simulated_trades
        WHERE strategy_name = %s
          AND status = 'open'
        ORDER BY opened_at ASC;
    """, (STRATEGY_NAME,))

    return cur.fetchall()


# -------------------------------------------------------------------
# PRECIO ACTUAL
# -------------------------------------------------------------------

def get_latest_price(cur, symbol):
    cur.execute("""
        SELECT price, collected_at
        FROM raw_tickers_24h
        WHERE symbol = %s
          AND price IS NOT NULL
        ORDER BY collected_at DESC
        LIMIT 1;
    """, (symbol,))

    return cur.fetchone()


# -------------------------------------------------------------------
# EVALUAR SALIDA
# -------------------------------------------------------------------

def evaluate_exit(trade, latest_price, price_time):
    (
        trade_id,
        experiment_run_id,
        token_id,
        symbol,
        capital_before,
        allocated_capital,
        quantity,
        entry_price_ideal,
        entry_price_realistic,
        stop_price,
        tp1_price,
        tp2_price,
        tp3_price,
        opened_at,
    ) = trade

    current_price = Decimal(latest_price)

    now = datetime.now(timezone.utc)

    # Primero validar timeout.
    # Si pasaron más de 24h, no usamos el precio actual para decidir STOP/TP.
    # Cerramos como TIMEOUT para no contaminar el experimento.
    if opened_at is not None:
        opened_at_utc = opened_at
        if opened_at_utc.tzinfo is None:
            opened_at_utc = opened_at_utc.replace(tzinfo=timezone.utc)

        hours_open = (now - opened_at_utc).total_seconds() / 3600

        if hours_open >= 24:
            return "TIMEOUT", current_price

    # Si todavía está dentro de la ventana válida, evaluamos niveles.
    if current_price <= Decimal(stop_price):
        return "STOP_LOSS", current_price

    if current_price >= Decimal(tp3_price):
        return "TP3", current_price

    if current_price >= Decimal(tp2_price):
        return "TP2", current_price

    if current_price >= Decimal(tp1_price):
        return "TP1", current_price

    return None, current_price

# -------------------------------------------------------------------
# CERRAR TRADE
# -------------------------------------------------------------------

def close_trade(cur, trade, exit_reason, exit_price):
    (
        trade_id,
        experiment_run_id,
        token_id,
        symbol,
        capital_before,
        allocated_capital,
        quantity,
        entry_price_ideal,
        entry_price_realistic,
        stop_price,
        tp1_price,
        tp2_price,
        tp3_price,
        opened_at,
    ) = trade

    entry_price = Decimal(entry_price_realistic)
    exit_price = Decimal(exit_price)
    allocated_capital = Decimal(allocated_capital)
    quantity = Decimal(quantity)

    gross_exit_value = quantity * exit_price
    gross_return_pct = ((exit_price - entry_price) / entry_price) * Decimal("100")

    total_fees_pct = ENTRY_FEE_PCT + EXIT_FEE_PCT
    net_return_pct = gross_return_pct - total_fees_pct

    profit_loss = allocated_capital * (net_return_pct / Decimal("100"))
    capital_after = Decimal(capital_before) + profit_loss

    cur.execute("""
        UPDATE simulated_trades
        SET
            status = 'closed',
            exit_price_ideal = %s,
            exit_price_realistic = %s,
            gross_return_pct = %s,
            fees_pct = %s,
            slippage_pct = 0,
            net_return_pct = %s,
            capital_after = %s,
            exit_reason = %s,
            closed_at = NOW()
        WHERE id = %s;
    """, (
        exit_price,
        exit_price,
        gross_return_pct,
        total_fees_pct,
        net_return_pct,
        capital_after,
        exit_reason,
        trade_id,
    ))

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
            'CLOSE',
            %s,
            jsonb_build_object(
                'exit_reason', %s,
                'entry_price', %s,
                'exit_price', %s,
                'gross_return_pct', %s,
                'fees_pct', %s,
                'net_return_pct', %s,
                'capital_after', %s
            )
        );
    """, (
        experiment_run_id,
        trade_id,
        symbol,
        f"Closed simulated trade for {symbol} by {exit_reason}",
        exit_reason,
        str(entry_price),
        str(exit_price),
        str(gross_return_pct),
        str(total_fees_pct),
        str(net_return_pct),
        str(capital_after),
    ))

    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "exit_reason": exit_reason,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "gross_return_pct": gross_return_pct,
        "net_return_pct": net_return_pct,
        "capital_after": capital_after,
    }


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------

def main():
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn:
            with conn.cursor() as cur:
                trades = get_open_trades(cur)

                if not trades:
                    print("No hay trades abiertos para evaluar.")
                    return

                print(f"Trades abiertos encontrados: {len(trades)}")

                for trade in trades:
                    symbol = trade[3]

                    latest = get_latest_price(cur, symbol)

                    if not latest:
                        print(f"[SKIP] {symbol}: no hay precio reciente.")
                        continue

                    latest_price, price_time = latest
                    exit_reason, exit_price = evaluate_exit(trade, latest_price, price_time)

                    print("-" * 80)
                    print(f"Trade: {symbol}")
                    print(f"Precio actual: {latest_price}")
                    print(f"Resultado evaluación: {exit_reason or 'SIN SALIDA'}")

                    if exit_reason:
                        result = close_trade(cur, trade, exit_reason, exit_price)
                        print(f"[TRADE CLOSED] {result['symbol']} | {result['exit_reason']}")
                        print(f"Net return: {result['net_return_pct']}")
                        print(f"Capital after: {result['capital_after']}")

        print("\nEvaluación terminada.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()