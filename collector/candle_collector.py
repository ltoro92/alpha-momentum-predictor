import json
import time
from decimal import Decimal
from typing import Any, Dict, List

import psycopg2
import requests


KLINES_URL = "https://www.binance.com/bapi/defi/v1/public/alpha-trade/klines"

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}


INTERVALS = {
    "1m": 120,
    "5m": 120,
    "15m": 120,
    "1h": 72,
}


def to_decimal(value: Any):
    if value is None:
        return None

    try:
        return Decimal(str(value))
    except Exception:
        return None


def millis_to_timestamp_sql(value: Any) -> float:
    return int(value) / 1000.0


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


def get_klines(symbol: str, interval: str, limit: int) -> List[List[Any]]:
    response = requests.get(
        KLINES_URL,
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()

    if payload.get("code") != "000000" or not payload.get("success"):
        raise RuntimeError(f"Klines inválidas para {symbol} {interval}: {payload}")

    data = payload.get("data", [])

    if not isinstance(data, list):
        raise RuntimeError(f"Klines sin data válida para {symbol} {interval}: {payload}")

    return data


def save_klines(token_id: str, symbol: str, interval: str, klines: List[List[Any]]) -> int:
    conn = psycopg2.connect(**DB_CONFIG)

    inserted_or_updated = 0

    try:
        with conn:
            with conn.cursor() as cur:
                for k in klines:
                    if len(k) < 11:
                        continue

                    open_time = k[0]
                    open_price = k[1]
                    high_price = k[2]
                    low_price = k[3]
                    close_price = k[4]
                    volume = k[5]
                    close_time = k[6]
                    quote_volume = k[7]

                    cur.execute(
                        """
                        INSERT INTO raw_candles (
                            token_id,
                            symbol,
                            interval,
                            open_time,
                            close_time,
                            open_price,
                            high_price,
                            low_price,
                            close_price,
                            volume,
                            quote_volume,
                            raw_payload,
                            collected_at
                        )
                        VALUES (
                            %s, %s, %s,
                            TO_TIMESTAMP(%s),
                            TO_TIMESTAMP(%s),
                            %s, %s, %s, %s, %s, %s, %s,
                            NOW()
                        )
                        ON CONFLICT (symbol, interval, open_time)
                        DO UPDATE SET
                            close_time = EXCLUDED.close_time,
                            open_price = EXCLUDED.open_price,
                            high_price = EXCLUDED.high_price,
                            low_price = EXCLUDED.low_price,
                            close_price = EXCLUDED.close_price,
                            volume = EXCLUDED.volume,
                            quote_volume = EXCLUDED.quote_volume,
                            raw_payload = EXCLUDED.raw_payload,
                            collected_at = NOW();
                        """,
                        (
                            token_id,
                            symbol,
                            interval,
                            millis_to_timestamp_sql(open_time),
                            millis_to_timestamp_sql(close_time),
                            to_decimal(open_price),
                            to_decimal(high_price),
                            to_decimal(low_price),
                            to_decimal(close_price),
                            to_decimal(volume),
                            to_decimal(quote_volume),
                            json.dumps(k),
                        ),
                    )

                    inserted_or_updated += 1

    finally:
        conn.close()

    return inserted_or_updated


def main() -> None:
    symbols = get_tradeable_symbols()
    print(f"Símbolos tradeables encontrados: {len(symbols)}")

    total_saved = 0
    failed = 0

    for item in symbols:
        token_id = item["token_id"]
        symbol = item["symbol"]

        for interval, limit in INTERVALS.items():
            try:
                klines = get_klines(symbol, interval, limit)
                saved = save_klines(token_id, symbol, interval, klines)
                total_saved += saved

                print(f"[OK] {symbol} {interval}: {saved} velas")

            except Exception as exc:
                failed += 1
                print(f"[ERROR] {symbol} {interval}: {exc}")

            time.sleep(0.15)

    print("Proceso terminado.")
    print(f"Velas guardadas/actualizadas: {total_saved}")
    print(f"Errores: {failed}")


if __name__ == "__main__":
    main()