import requests
import psycopg2
from psycopg2.extras import Json
from decimal import Decimal


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}

TICKER_URL = "https://www.binance.com/bapi/defi/v1/public/alpha-trade/ticker"


def get_open_trade_symbols(cur):
    cur.execute("""
        SELECT DISTINCT
            t.symbol,
            t.token_id
        FROM simulated_trades t
        WHERE t.status = 'open'
        ORDER BY t.symbol;
    """)
    return cur.fetchall()


def fetch_ticker(symbol):
    response = requests.get(
        TICKER_URL,
        params={"symbol": symbol},
        timeout=20
    )
    response.raise_for_status()

    payload = response.json()

    if not payload.get("success"):
        raise ValueError(f"Ticker inválido para {symbol}: {payload}")

    return payload


def to_decimal(value):
    if value is None:
        return None
    return Decimal(str(value))


def save_ticker(cur, symbol, token_id, payload):
    data = payload.get("data", {})

    cur.execute("""
        INSERT INTO raw_tickers_24h (
            token_id,
            symbol,
            price,
            price_change_pct,
            high_price,
            low_price,
            volume,
            quote_volume,
            raw_payload,
            exchange_time
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, 
            TO_TIMESTAMP(%s / 1000.0)
        );
    """, (
        token_id,
        symbol,
        to_decimal(data.get("lastPrice")),
        to_decimal(data.get("priceChangePercent")),
        to_decimal(data.get("highPrice")),
        to_decimal(data.get("lowPrice")),
        to_decimal(data.get("volume")),
        to_decimal(data.get("quoteVolume")),
        Json(payload),
        data.get("closeTime"),
    ))


def main():
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn:
            with conn.cursor() as cur:
                open_symbols = get_open_trade_symbols(cur)

                if not open_symbols:
                    print("No hay trades abiertos para actualizar.")
                    return

                print(f"Trades abiertos a actualizar: {len(open_symbols)}")

                saved = 0
                errors = 0

                for symbol, token_id in open_symbols:
                    try:
                        payload = fetch_ticker(symbol)
                        save_ticker(cur, symbol, token_id, payload)

                        last_price = payload["data"].get("lastPrice")
                        change_pct = payload["data"].get("priceChangePercent")

                        print(f"[OK] {symbol} price={last_price} 24h={change_pct}%")
                        saved += 1

                    except Exception as exc:
                        print(f"[ERROR] {symbol}: {exc}")
                        errors += 1

                print("-" * 80)
                print(f"Tickers actualizados: {saved}")
                print(f"Errores: {errors}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()