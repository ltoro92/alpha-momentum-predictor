import requests
import psycopg2
from psycopg2.extras import Json


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}

TOKEN_LIST_URL = "https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list"
TICKER_URL = "https://www.binance.com/bapi/defi/v1/public/alpha-trade/ticker"


def fetch_alpha_token_list():
    response = requests.get(TOKEN_LIST_URL, timeout=30)
    response.raise_for_status()

    payload = response.json()

    if not payload.get("success"):
        raise ValueError(f"Token list inválida: {payload}")

    return payload.get("data", [])


def is_ticker_valid(symbol):
    try:
        response = requests.get(
            TICKER_URL,
            params={"symbol": symbol},
            timeout=15
        )
        response.raise_for_status()

        payload = response.json()
        return bool(payload.get("success"))

    except Exception:
        return False


def upsert_token(cur, token, trading_symbol):
    cur.execute("""
        INSERT INTO raw_tokens (
            alpha_token_id,
            symbol,
            name,
            source,
            is_active,
            raw_payload,
            first_seen_at,
            last_seen_at
        )
        VALUES (
            %s, %s, %s,
            'binance_alpha_token_list',
            TRUE,
            %s,
            NOW(),
            NOW()
        )
        ON CONFLICT (symbol)
        DO UPDATE SET
            alpha_token_id = EXCLUDED.alpha_token_id,
            name = EXCLUDED.name,
            source = EXCLUDED.source,
            is_active = TRUE,
            raw_payload = EXCLUDED.raw_payload,
            last_seen_at = NOW();
    """, (
        token.get("tokenId") or token.get("alphaId"),
        trading_symbol,
        token.get("name") or token.get("symbol"),
        Json(token),
    ))


def main():
    tokens = fetch_alpha_token_list()

    print(f"Tokens recibidos desde Alpha token list: {len(tokens)}")

    inserted_or_updated = 0
    skipped = 0
    invalid_ticker = 0

    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn:
            with conn.cursor() as cur:
                for token in tokens:
                    alpha_id = token.get("alphaId")
                    token_symbol = token.get("symbol")
                    offline = token.get("offline")

                    if not alpha_id:
                        skipped += 1
                        continue

                    if offline is True:
                        skipped += 1
                        continue

                    trading_symbol = f"{alpha_id}USDT"

                    # Validamos ticker porque exchange-info puede no traer tokens nuevos.
                    if not is_ticker_valid(trading_symbol):
                        invalid_ticker += 1
                        continue

                    upsert_token(cur, token, trading_symbol)
                    inserted_or_updated += 1

                    if token_symbol and token_symbol.upper() == "ZEST":
                        print(f"[FOUND ZEST] {trading_symbol} | {token.get('name')} | price={token.get('price')} | 24h={token.get('percentChange24h')}%")

    finally:
        conn.close()

    print("-" * 80)
    print(f"Insertados/actualizados: {inserted_or_updated}")
    print(f"Omitidos: {skipped}")
    print(f"Tickers inválidos: {invalid_ticker}")


if __name__ == "__main__":
    main()