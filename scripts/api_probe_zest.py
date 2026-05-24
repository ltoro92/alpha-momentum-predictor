import requests
import json


TOKEN_LIST_URL = "https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list"
EXCHANGE_INFO_URL = "https://www.binance.com/bapi/defi/v1/public/alpha-trade/get-exchange-info"
TICKER_URL = "https://www.binance.com/bapi/defi/v1/public/alpha-trade/ticker"


def print_json(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def find_zest_in_token_list():
    print("\n--- BUSCANDO ZEST EN TOKEN LIST ---")
    response = requests.get(TOKEN_LIST_URL, timeout=30)
    response.raise_for_status()
    payload = response.json()

    data = payload.get("data", [])
    matches = []

    for token in data:
        text = json.dumps(token, ensure_ascii=False).lower()
        if "zest" in text:
            matches.append(token)

    print(f"Matches token list: {len(matches)}")

    for item in matches:
        print_json({
            "tokenId": item.get("tokenId"),
            "alphaId": item.get("alphaId"),
            "symbol": item.get("symbol"),
            "name": item.get("name"),
            "price": item.get("price"),
            "percentChange24h": item.get("percentChange24h"),
            "volume24h": item.get("volume24h"),
            "contractAddress": item.get("contractAddress"),
            "chainName": item.get("chainName"),
            "listingTime": item.get("listingTime"),
            "listingCex": item.get("listingCex"),
            "offline": item.get("offline"),
        })

    return matches


def find_zest_in_exchange_info():
    print("\n--- BUSCANDO ZEST EN EXCHANGE INFO ---")
    response = requests.get(EXCHANGE_INFO_URL, timeout=30)
    response.raise_for_status()
    payload = response.json()

    symbols = payload.get("data", {}).get("symbols", [])
    matches = []

    for symbol in symbols:
        text = json.dumps(symbol, ensure_ascii=False).lower()
        if "zest" in text:
            matches.append(symbol)

    print(f"Matches exchange-info: {len(matches)}")

    for item in matches:
        print_json(item)

    return matches


def try_tickers(symbols):
    print("\n--- PROBANDO TICKERS POSIBLES ---")

    candidates = set()

    for s in symbols:
        if isinstance(s, str):
            candidates.add(s)

    # Intentos obvios
    candidates.update([
        "ZESTUSDT",
        "ZEST",
        "ALPHA_ZESTUSDT",
    ])

    for symbol in sorted(candidates):
        print(f"\nProbando ticker: {symbol}")
        try:
            response = requests.get(
                TICKER_URL,
                params={"symbol": symbol},
                timeout=20
            )
            print(f"Status HTTP: {response.status_code}")
            payload = response.json()
            print_json(payload)
        except Exception as exc:
            print(f"ERROR: {exc}")


def main():
    token_matches = find_zest_in_token_list()
    exchange_matches = find_zest_in_exchange_info()

    possible_symbols = []

    for token in token_matches:
        alpha_id = token.get("alphaId")
        symbol = token.get("symbol")

        if alpha_id:
            possible_symbols.append(f"{alpha_id}USDT")

        if symbol:
            possible_symbols.append(f"{symbol}USDT")

    for item in exchange_matches:
        if item.get("symbol"):
            possible_symbols.append(item.get("symbol"))

    try_tickers(possible_symbols)


if __name__ == "__main__":
    main()