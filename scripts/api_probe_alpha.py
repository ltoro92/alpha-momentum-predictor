import json
import time
from typing import Any, Dict, List, Optional

import requests


BASE_URL = "https://www.binance.com"

TOKEN_LIST_URL = (
    f"{BASE_URL}/bapi/defi/v1/public/wallet-direct/buw/"
    "wallet/cex/alpha/all/token/list"
)

EXCHANGE_INFO_URL = (
    f"{BASE_URL}/bapi/defi/v1/public/alpha-trade/get-exchange-info"
)

TICKER_URL = f"{BASE_URL}/bapi/defi/v1/public/alpha-trade/ticker"
KLINES_URL = f"{BASE_URL}/bapi/defi/v1/public/alpha-trade/klines"
FULL_DEPTH_URL = f"{BASE_URL}/bapi/defi/v1/public/alpha-trade/fullDepth"


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    response = requests.get(url, params=params, timeout=20)
    print(f"URL: {response.url}")
    print(f"Status: {response.status_code}")

    if response.status_code != 200:
        print(response.text[:1000])
        response.raise_for_status()

    return response.json()


def get_alpha_token_list() -> List[Dict[str, Any]]:
    print("\n--- 1. PROBANDO ALPHA TOKEN LIST ---")
    data = get_json(TOKEN_LIST_URL)

    print("Respuesta base:")
    print_json({
        "code": data.get("code"),
        "success": data.get("success"),
        "message": data.get("message"),
        "data_type": type(data.get("data")).__name__,
        "data_len": len(data.get("data", [])) if isinstance(data.get("data"), list) else None,
    })

    tokens = data.get("data", [])
    if not isinstance(tokens, list):
        raise ValueError("Token list no devolvió una lista en data")

    print(f"Total tokens Alpha encontrados: {len(tokens)}")

    if tokens:
        print("\nEjemplo primer token:")
        print_json(tokens[0])

    return tokens


def get_alpha_exchange_info() -> Dict[str, Any]:
    print("\n--- 2. PROBANDO ALPHA EXCHANGE INFO ---")
    data = get_json(EXCHANGE_INFO_URL)

    payload = data.get("data", {})
    symbols = payload.get("symbols", []) if isinstance(payload, dict) else []

    print("Resumen exchange info:")
    print_json({
        "code": data.get("code"),
        "success": data.get("success"),
        "timezone": payload.get("timezone") if isinstance(payload, dict) else None,
        "symbols_len": len(symbols),
    })

    if symbols:
        print("\nEjemplo símbolo Alpha:")
        print_json(symbols[0])

    return data


def choose_tradable_alpha_symbol(exchange_info: Dict[str, Any]) -> str:
    symbols_payload = exchange_info.get("data", {}).get("symbols", [])

    tradable_symbols = [
        item["symbol"]
        for item in symbols_payload
        if item.get("status") == "TRADING"
        and item.get("quoteAsset") == "USDT"
        and item.get("symbol")
    ]

    if not tradable_symbols:
        raise ValueError("No se encontraron símbolos Alpha tradeables con USDT")

    return tradable_symbols[0]


def get_ticker(symbol: str) -> Dict[str, Any]:
    print(f"\n--- 3. PROBANDO ALPHA TICKER 24H: {symbol} ---")
    data = get_json(TICKER_URL, params={"symbol": symbol})
    print_json(data)
    return data


def get_klines(symbol: str, interval: str = "15m", limit: int = 3) -> Dict[str, Any]:
    print(f"\n--- 4. PROBANDO ALPHA KLINES: {symbol}, {interval}, limit={limit} ---")
    data = get_json(
        KLINES_URL,
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
    )

    payload = data.get("data", [])
    print(f"Klines recibidas: {len(payload) if isinstance(payload, list) else 'N/A'}")

    if isinstance(payload, list) and payload:
        print("Última kline:")
        print_json(payload[-1])
    else:
        print_json(data)

    return data


def get_full_depth(symbol: str, limit: int = 5) -> Dict[str, Any]:
    print(f"\n--- 5. PROBANDO ALPHA FULL DEPTH: {symbol}, limit={limit} ---")
    data = get_json(
        FULL_DEPTH_URL,
        params={
            "symbol": symbol,
            "limit": limit,
        },
    )

    payload = data.get("data", {})
    if isinstance(payload, dict):
        print("Resumen order book:")
        print_json({
            "lastUpdateId": payload.get("lastUpdateId"),
            "symbol": payload.get("symbol"),
            "top_bids": payload.get("bids", [])[:3],
            "top_asks": payload.get("asks", [])[:3],
        })
    else:
        print_json(data)

    return data


if __name__ == "__main__":
    print("Iniciando validación de APIs Binance Alpha...")

    get_alpha_token_list()
    time.sleep(1)

    exchange_info = get_alpha_exchange_info()
    time.sleep(1)

    test_symbol = choose_tradable_alpha_symbol(exchange_info)

    print(f"\nSímbolo Alpha tradeable elegido para prueba: {test_symbol}")

    time.sleep(1)
    get_ticker(test_symbol)

    time.sleep(1)
    get_klines(test_symbol, interval="15m", limit=3)

    time.sleep(1)
    get_full_depth(test_symbol, limit=5)

    print("\nValidación Alpha finalizada.")