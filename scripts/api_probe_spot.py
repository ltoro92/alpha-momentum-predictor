import requests
import json
import time

# Base URL para la API pública de Binance
BINANCE_API_URL = "https://api.binance.com/api/v3"

def print_json(data):
    """Imprime diccionarios en formato JSON legible."""
    print(json.dumps(data, indent=2))

def get_exchange_info():
    """
    Obtiene la lista completa de símbolos y sus reglas de trading.
    Nos sirve para filtrar cuáles están operables.
    """
    print("\n--- 1. PROBANDO /exchangeInfo ---")
    url = f"{BINANCE_API_URL}/exchangeInfo"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        print(f"Total de símbolos devueltos: {len(data['symbols'])}")
        
        # Filtramos solo uno como ejemplo (ej. BTCUSDT)
        sample_symbol = next((s for s in data['symbols'] if s['symbol'] == 'BTCUSDT'), None)
        if sample_symbol:
            print("Ejemplo de payload para BTCUSDT:")
            print_json(sample_symbol)
    else:
        print(f"Error {response.status_code}: {response.text}")

def get_ticker_24h(symbol="BTCUSDT"):
    """Obtiene el resumen de las últimas 24hs para un símbolo."""
    print(f"\n--- 2. PROBANDO /ticker/24hr para {symbol} ---")
    url = f"{BINANCE_API_URL}/ticker/24hr"
    params = {"symbol": symbol}
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        print_json(response.json())
    else:
        print(f"Error {response.status_code}: {response.text}")

def get_klines(symbol="BTCUSDT", interval="15m", limit=5):
    """Obtiene velas (klines) para un símbolo."""
    print(f"\n--- 3. PROBANDO /klines para {symbol} (Intervalo: {interval}, Límite: {limit}) ---")
    url = f"{BINANCE_API_URL}/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        data = response.json()
        print(f"Se obtuvieron {len(data)} velas.")
        print("Ejemplo de la última vela (formato lista cruda de Binance):")
        if data:
            print(data[-1])
            # Binance devuelve arrays sin nombres de claves.
            # El orden es: [Open time, Open, High, Low, Close, Volume, Close time, Quote asset volume, Number of trades, Taker buy base asset volume, Taker buy quote asset volume, Ignore]
    else:
        print(f"Error {response.status_code}: {response.text}")

def get_order_book(symbol="BTCUSDT", limit=10):
    """Obtiene el libro de órdenes (depth)."""
    print(f"\n--- 4. PROBANDO /depth para {symbol} (Límite: {limit}) ---")
    url = f"{BINANCE_API_URL}/depth"
    params = {
        "symbol": symbol,
        "limit": limit
    }
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        data = response.json()
        print(f"Último Update ID: {data.get('lastUpdateId')}")
        print("Top 3 Bids (Compradores):")
        print(data.get('bids', [])[:3])
        print("Top 3 Asks (Vendedores):")
        print(data.get('asks', [])[:3])
    else:
        print(f"Error {response.status_code}: {response.text}")

if __name__ == "__main__":
    print("Iniciando validación de APIs de Binance...")
    
    # 1. Probar exchange info
    get_exchange_info()
    time.sleep(1) # Respetando rate limits básicos
    
    # Vamos a usar una moneda que suele ser muy volátil o "Alpha" como ejemplo, o BTC.
    test_symbol = "PEPEUSDT" 
    
    # 2. Probar ticker
    get_ticker_24h(test_symbol)
    time.sleep(1)
    
    # 3. Probar velas
    get_klines(test_symbol, interval="15m", limit=3)
    time.sleep(1)
    
    # 4. Probar Order Book
    get_order_book(test_symbol, limit=5)
    
    print("\nValidación finalizada. Revisa los payloads devueltos para diseñar tus parsers.")