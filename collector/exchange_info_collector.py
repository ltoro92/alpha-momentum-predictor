import json
from typing import Any, Dict, List

import psycopg2
import requests


EXCHANGE_INFO_URL = (
    "https://www.binance.com/bapi/defi/v1/public/alpha-trade/get-exchange-info"
)

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}


def get_exchange_info_symbols() -> List[Dict[str, Any]]:
    response = requests.get(EXCHANGE_INFO_URL, timeout=20)
    response.raise_for_status()

    payload = response.json()

    if payload.get("code") != "000000" or not payload.get("success"):
        raise RuntimeError(f"Respuesta inválida de Binance Alpha exchangeInfo: {payload}")

    data = payload.get("data", {})
    symbols = data.get("symbols", [])

    if not isinstance(symbols, list):
        raise RuntimeError("El campo data.symbols no es una lista")

    return symbols


def save_tradeable_symbols(symbols: List[Dict[str, Any]]) -> None:
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn:
            with conn.cursor() as cur:
                count = 0

                for item in symbols:
                    symbol = item.get("symbol")
                    status = item.get("status")
                    quote_asset = item.get("quoteAsset")
                    base_asset = item.get("baseAsset")

                    if not symbol:
                        continue

                    if status != "TRADING" or quote_asset != "USDT":
                        continue

                    # ALPHA_105USDT -> ALPHA_105
                    alpha_token_id = base_asset

                    cur.execute(
                        """
                        INSERT INTO raw_tokens (
                            alpha_token_id,
                            symbol,
                            name,
                            raw_payload,
                            is_active,
                            last_seen_at
                        )
                        VALUES (%s, %s, %s, %s, TRUE, NOW())
                        ON CONFLICT (symbol)
                        DO UPDATE SET
                            alpha_token_id = EXCLUDED.alpha_token_id,
                            raw_payload = EXCLUDED.raw_payload,
                            is_active = TRUE,
                            last_seen_at = NOW();
                        """,
                        (
                            alpha_token_id,
                            symbol,
                            symbol,
                            json.dumps(item),
                        ),
                    )

                    count += 1

                print(f"Símbolos tradeables USDT guardados/actualizados: {count}")

    finally:
        conn.close()


def main() -> None:
    print("Descargando exchangeInfo Alpha...")
    symbols = get_exchange_info_symbols()
    print(f"Símbolos recibidos desde exchangeInfo: {len(symbols)}")

    save_tradeable_symbols(symbols)

    print("Listo. Símbolos tradeables guardados en raw_tokens.")


if __name__ == "__main__":
    main()