import psycopg2


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}


TABLES = [
    "raw_tokens",
    "raw_tickers_24h",
    "raw_candles",
    "raw_order_book_snapshots",
    "features",
    "signals",
    "simulated_trades",
    "performance_reports",
    "audit_events",
    "collector_logs",
    "signal_logs",
    "trade_logs",
    "error_logs",
]


def main() -> None:
    print("Verificando conexión a PostgreSQL...")

    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT NOW();")
            db_time = cur.fetchone()[0]
            print(f"Conexión OK. Hora DB: {db_time}")

            print("\nConteo de tablas:")
            for table in TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {table};")
                count = cur.fetchone()[0]
                print(f"- {table}: {count}")

            print("\nVerificando vista v_tradeable_tokens...")
            cur.execute(
                """
                SELECT trading_symbol, display_symbol, display_name
                FROM v_tradeable_tokens
                WHERE trading_symbol = 'ALPHA_681USDT'
                LIMIT 1;
                """
            )
            row = cur.fetchone()

            if row:
                print(f"WARD mapping OK: {row[0]} = {row[1]} / {row[2]}")
            else:
                print("No se encontró mapping para ALPHA_681USDT")

    finally:
        conn.close()


if __name__ == "__main__":
    main()