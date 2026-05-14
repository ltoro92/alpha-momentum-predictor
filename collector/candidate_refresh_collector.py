import json
import time
from decimal import Decimal
from typing import Any, Dict, List

import psycopg2
import requests


TICKER_URL = "https://www.binance.com/bapi/defi/v1/public/alpha-trade/ticker"
KLINES_URL = "https://www.binance.com/bapi/defi/v1/public/alpha-trade/klines"
FULL_DEPTH_URL = "https://www.binance.com/bapi/defi/v1/public/alpha-trade/fullDepth"

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}

MIN_PRICE_CHANGE_24H = Decimal("-10")
MAX_PRICE_CHANGE_24H = Decimal("25")
MIN_QUOTE_VOLUME_USDT = Decimal("50000")

DEPTH_LIMIT = 20

INTERVALS = {
    "1m": 60,
    "5m": 60,
    "15m": 60,
    "1h": 30,
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
                WHERE symbol LIKE 'ALPHA_%%USDT'
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


def save_ticker(conn, token_id: str, symbol: str, ticker: Dict[str, Any]) -> None:
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


def is_candidate(ticker: Dict[str, Any]) -> bool:
    change = to_decimal(ticker.get("priceChangePercent"))
    quote_volume = to_decimal(ticker.get("quoteVolume"))

    if change is None or quote_volume is None:
        return False

    return (
        change >= MIN_PRICE_CHANGE_24H
        and change <= MAX_PRICE_CHANGE_24H
        and quote_volume >= MIN_QUOTE_VOLUME_USDT
    )


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


def save_klines(conn, token_id: str, symbol: str, interval: str, klines: List[List[Any]]) -> int:
    saved = 0

    with conn.cursor() as cur:
        for k in klines:
            if len(k) < 11:
                continue

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
                    millis_to_timestamp_sql(k[0]),
                    millis_to_timestamp_sql(k[6]),
                    to_decimal(k[1]),
                    to_decimal(k[2]),
                    to_decimal(k[3]),
                    to_decimal(k[4]),
                    to_decimal(k[5]),
                    to_decimal(k[7]),
                    json.dumps(k),
                ),
            )

            saved += 1

    return saved


def get_order_book(symbol: str) -> Dict[str, Any]:
    response = requests.get(
        FULL_DEPTH_URL,
        params={
            "symbol": symbol,
            "limit": DEPTH_LIMIT,
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


def save_order_book(conn, token_id: str, symbol: str, order_book: Dict[str, Any]) -> None:
    metrics = calculate_order_book_metrics(order_book)

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


def main() -> None:
    symbols = get_tradeable_symbols()

    print(f"Símbolos tradeables encontrados: {len(symbols)}")
    print("Actualizando tickers y detectando candidatos...")

    candidates = []
    ticker_saved = 0
    ticker_failed = 0

    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn:
            for item in symbols:
                token_id = item["token_id"]
                symbol = item["symbol"]

                try:
                    ticker = get_ticker(symbol)
                    save_ticker(conn, token_id, symbol, ticker)
                    ticker_saved += 1

                    if is_candidate(ticker):
                        candidates.append(
                            {
                                "token_id": token_id,
                                "symbol": symbol,
                                "ticker": ticker,
                            }
                        )

                except Exception as exc:
                    ticker_failed += 1
                    print(f"[TICKER ERROR] {symbol}: {exc}")

                time.sleep(0.10)

        print(f"Tickers guardados: {ticker_saved}")
        print(f"Errores ticker: {ticker_failed}")
        print(f"Candidatos detectados: {len(candidates)}")

        candle_saved = 0
        candle_failed = 0
        order_book_saved = 0
        order_book_failed = 0

        with conn:
            for item in candidates:
                token_id = item["token_id"]
                symbol = item["symbol"]

                for interval, limit in INTERVALS.items():
                    try:
                        klines = get_klines(symbol, interval, limit)
                        saved = save_klines(conn, token_id, symbol, interval, klines)
                        candle_saved += saved

                    except Exception as exc:
                        candle_failed += 1
                        print(f"[CANDLE ERROR] {symbol} {interval}: {exc}")

                    time.sleep(0.10)

                try:
                    order_book = get_order_book(symbol)
                    save_order_book(conn, token_id, symbol, order_book)
                    order_book_saved += 1

                except Exception as exc:
                    order_book_failed += 1
                    print(f"[ORDER BOOK ERROR] {symbol}: {exc}")

                time.sleep(0.10)

        print("Proceso terminado.")
        print(f"Candidatos actualizados: {len(candidates)}")
        print(f"Velas guardadas/actualizadas: {candle_saved}")
        print(f"Errores velas: {candle_failed}")
        print(f"Order books guardados: {order_book_saved}")
        print(f"Errores order book: {order_book_failed}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()