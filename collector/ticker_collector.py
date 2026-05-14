import json
import time
from decimal import Decimal
from typing import Any, Dict, List

import psycopg2
import requests


TICKER_URL = "https://www.binance.com/bapi/defi/v1/public/alpha-trade/ticker"

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}


def get_tradeable_symbols() -> List[Dict[str, Any]]:
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, symbol
                FROM raw_tokens
                WHERE symbol LIKE 'ALPHA_%USDT'
                AND is_active = TRUE
                ORDER BY symbol;
                """
            )

            rows = cur.fetchall()

            return [
                {
                    "token_id": row[0],
                    "symbol": row[1],
                }
                for row in rows
            ]

    finally:
        conn.close()


def get_ticker(symbol: str) -> Dict[str, Any]:
    response = requests.get(
        TICKER_URL,
        params={"symbol": symbol},
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()

    if payload.get("code") != "000000" or not payload.get("success"):
        raise RuntimeError(f"Ticker inválido para {symbol}: {payload}")

    data = payload.get("data")

    if not isinstance(data, dict):
        raise RuntimeError(f"Ticker sin data válida para {symbol}: {payload}")

    return data


def to_decimal(value: Any):
    if value is None:
        return None

    try:
        return Decimal(str(value))
    except Exception:
        return None


def save_ticker(token_id: str, symbol: str, ticker: Dict[str, Any]) -> None:
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
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
                        exchange_time,
                        collected_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        TO_TIMESTAMP(%s / 1000.0),
                        NOW()
                    );
                    """,
                    (
                        token_id,
                        symbol,
                        to_decimal(ticker.get("lastPrice")),
                        to_decimal(ticker.get("priceChangePercent")),
                        to_decimal(ticker.get("highPrice")),
                        to_decimal(ticker.get("lowPrice")),
                        to_decimal(ticker.get("volume")),
                        to_decimal(ticker.get("quoteVolume")),
                        json.dumps(ticker),
                        ticker.get("closeTime"),
                    ),
                )

    finally:
        conn.close()


def main() -> None:
    symbols = get_tradeable_symbols()
    print(f"Símbolos tradeables encontrados: {len(symbols)}")

    saved = 0
    failed = 0

    for item in symbols:
        token_id = item["token_id"]
        symbol = item["symbol"]

        try:
            ticker = get_ticker(symbol)
            save_ticker(token_id, symbol, ticker)
            saved += 1
            print(f"[OK] {symbol}")

        except Exception as exc:
            failed += 1
            print(f"[ERROR] {symbol}: {exc}")

        time.sleep(0.15)

    print("Proceso terminado.")
    print(f"Tickers guardados: {saved}")
    print(f"Errores: {failed}")


if __name__ == "__main__":
    main()