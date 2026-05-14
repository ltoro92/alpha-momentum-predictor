import json
import time
from decimal import Decimal
from typing import Any, Dict, List

import psycopg2
import requests


FULL_DEPTH_URL = "https://www.binance.com/bapi/defi/v1/public/alpha-trade/fullDepth"

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}

DEPTH_LIMIT = 20
MIN_QUOTE_VOLUME_USDT = 50000
MIN_PRICE_CHANGE_24H = -10
MAX_PRICE_CHANGE_24H = 25


def to_decimal(value: Any):
    if value is None:
        return None

    try:
        return Decimal(str(value))
    except Exception:
        return None


def get_candidate_symbols() -> List[Dict[str, Any]]:
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH latest_tickers AS (
                    SELECT DISTINCT ON (symbol)
                        token_id,
                        symbol,
                        price_change_pct,
                        quote_volume,
                        collected_at
                    FROM raw_tickers_24h
                    WHERE symbol LIKE 'ALPHA_%%USDT'
                    ORDER BY symbol, collected_at DESC
                )
                SELECT
                    token_id,
                    symbol,
                    price_change_pct,
                    quote_volume
                FROM latest_tickers
                WHERE price_change_pct BETWEEN %s AND %s
                AND quote_volume >= %s
                ORDER BY price_change_pct DESC;
                """,
                (
                    MIN_PRICE_CHANGE_24H,
                    MAX_PRICE_CHANGE_24H,
                    MIN_QUOTE_VOLUME_USDT,
                ),
            )

            rows = cur.fetchall()

            return [
                {
                    "token_id": row[0],
                    "symbol": row[1],
                    "price_change_pct": row[2],
                    "quote_volume": row[3],
                }
                for row in rows
            ]

    finally:
        conn.close()


def get_order_book(symbol: str, limit: int = DEPTH_LIMIT) -> Dict[str, Any]:
    response = requests.get(
        FULL_DEPTH_URL,
        params={
            "symbol": symbol,
            "limit": limit,
        },
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()

    if payload.get("code") != "000000" or not payload.get("success"):
        raise RuntimeError(f"Order book inválido para {symbol}: {payload}")

    data = payload.get("data")

    if not isinstance(data, dict):
        raise RuntimeError(f"Order book sin data válida para {symbol}: {payload}")

    return data


def calculate_order_book_metrics(order_book: Dict[str, Any]) -> Dict[str, Any]:
    bids = order_book.get("bids", [])
    asks = order_book.get("asks", [])

    if not bids or not asks:
        raise RuntimeError("Order book sin bids o asks")

    best_bid = to_decimal(bids[0][0])
    best_ask = to_decimal(asks[0][0])

    if best_bid is None or best_ask is None:
        raise RuntimeError("No se pudo calcular best bid/ask")

    mid_price = (best_bid + best_ask) / Decimal("2")
    spread_pct = ((best_ask - best_bid) / mid_price) * Decimal("100")

    total_bid_liquidity = Decimal("0")
    total_ask_liquidity = Decimal("0")

    for price, qty in bids:
        price_dec = to_decimal(price)
        qty_dec = to_decimal(qty)

        if price_dec is not None and qty_dec is not None:
            total_bid_liquidity += price_dec * qty_dec

    for price, qty in asks:
        price_dec = to_decimal(price)
        qty_dec = to_decimal(qty)

        if price_dec is not None and qty_dec is not None:
            total_ask_liquidity += price_dec * qty_dec

    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid_price": mid_price,
        "spread_pct": spread_pct,
        "total_bid_liquidity": total_bid_liquidity,
        "total_ask_liquidity": total_ask_liquidity,
    }


def save_order_book(token_id: str, symbol: str, order_book: Dict[str, Any]) -> None:
    metrics = calculate_order_book_metrics(order_book)

    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO raw_order_book_snapshots (
                        token_id,
                        symbol,
                        depth_limit,
                        best_bid,
                        best_ask,
                        mid_price,
                        spread_pct,
                        total_bid_liquidity,
                        total_ask_liquidity,
                        bids,
                        asks,
                        raw_payload,
                        collected_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    );
                    """,
                    (
                        token_id,
                        symbol,
                        DEPTH_LIMIT,
                        metrics["best_bid"],
                        metrics["best_ask"],
                        metrics["mid_price"],
                        metrics["spread_pct"],
                        metrics["total_bid_liquidity"],
                        metrics["total_ask_liquidity"],
                        json.dumps(order_book.get("bids", [])),
                        json.dumps(order_book.get("asks", [])),
                        json.dumps(order_book),
                    ),
                )

    finally:
        conn.close()


def main() -> None:
    candidates = get_candidate_symbols()
    print(f"Candidatos para order book: {len(candidates)}")

    saved = 0
    failed = 0

    for item in candidates:
        token_id = item["token_id"]
        symbol = item["symbol"]
        change = item["price_change_pct"]
        quote_volume = item["quote_volume"]

        try:
            order_book = get_order_book(symbol, DEPTH_LIMIT)
            save_order_book(token_id, symbol, order_book)

            saved += 1
            print(f"[OK] {symbol} | 24h={change}% | quoteVol={quote_volume}")

        except Exception as exc:
            failed += 1
            print(f"[ERROR] {symbol}: {exc}")

        time.sleep(0.15)

    print("Proceso terminado.")
    print(f"Order books guardados: {saved}")
    print(f"Errores: {failed}")


if __name__ == "__main__":
    main()