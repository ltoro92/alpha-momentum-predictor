import json
from typing import Any, Dict, List

import psycopg2
import requests


TOKEN_LIST_URL = (
    "https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/"
    "wallet/cex/alpha/all/token/list"
)

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}


def get_alpha_tokens() -> List[Dict[str, Any]]:
    response = requests.get(TOKEN_LIST_URL, timeout=20)
    response.raise_for_status()

    payload = response.json()

    if payload.get("code") != "000000" or not payload.get("success"):
        raise RuntimeError(f"Respuesta inválida de Binance Alpha: {payload}")

    data = payload.get("data", [])

    if not isinstance(data, list):
        raise RuntimeError("El campo data no es una lista")

    return data


def save_tokens(tokens: List[Dict[str, Any]]) -> None:
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn:
            with conn.cursor() as cur:
                for token in tokens:
                    alpha_token_id = token.get("alphaId")
                    symbol = token.get("symbol")
                    name = token.get("name")

                    if not symbol:
                        continue

                    cur.execute(
                        """
                        INSERT INTO raw_tokens (
                            alpha_token_id,
                            symbol,
                            name,
                            raw_payload,
                            last_seen_at
                        )
                        VALUES (%s, %s, %s, %s, NOW())
                        ON CONFLICT (symbol)
                        DO UPDATE SET
                            alpha_token_id = EXCLUDED.alpha_token_id,
                            name = EXCLUDED.name,
                            raw_payload = EXCLUDED.raw_payload,
                            last_seen_at = NOW(),
                            is_active = TRUE;
                        """,
                        (
                            alpha_token_id,
                            symbol,
                            name,
                            json.dumps(token),
                        ),
                    )
    finally:
        conn.close()


def main() -> None:
    print("Descargando tokens Alpha...")
    tokens = get_alpha_tokens()
    print(f"Tokens recibidos: {len(tokens)}")

    print("Guardando tokens en PostgreSQL...")
    save_tokens(tokens)

    print("Listo. Tokens guardados en raw_tokens.")


if __name__ == "__main__":
    main()