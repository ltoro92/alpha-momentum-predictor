from decimal import Decimal
from typing import Any, Dict, List, Optional
import psycopg2

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

RELATIVE_VOLUME_LOOKBACK = 20

EXTREME_PUMP_PCT = Decimal("60")
STRONG_DROP_PCT = Decimal("-10")

def pct_change(current: Decimal, previous: Decimal) -> Optional[Decimal]:
    if previous is None or previous == 0:
        return None
    return ((current - previous) / previous) * Decimal("100")

def get_latest_tickers(conn) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""
            WITH latest_tickers AS (
                SELECT DISTINCT ON (symbol)
                    token_id,
                    symbol,
                    price,
                    price_change_pct,
                    high_price,
                    low_price,
                    quote_volume,
                    collected_at
                FROM raw_tickers_24h
                WHERE symbol LIKE 'ALPHA_%%USDT'
                ORDER BY symbol, collected_at DESC
            )
            SELECT token_id,symbol,price,price_change_pct,high_price,low_price,quote_volume
            FROM latest_tickers
            WHERE price_change_pct BETWEEN %s AND %s
            AND quote_volume >= %s
            ORDER BY price_change_pct DESC;
        """,(MIN_PRICE_CHANGE_24H,MAX_PRICE_CHANGE_24H,MIN_QUOTE_VOLUME_USDT))
        rows = cur.fetchall()

    return [{
        "token_id": r[0],
        "symbol": r[1],
        "price": r[2],
        "price_change_24h_pct": r[3],
        "high_price": r[4],
        "low_price": r[5],
        "quote_volume": r[6],
    } for r in rows]

def get_candles(conn,symbol:str,interval:str,limit:int)->List[Dict[str,Any]]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT open_time,open_price,high_price,low_price,close_price,volume,quote_volume
            FROM raw_candles
            WHERE symbol=%s AND interval=%s
            ORDER BY open_time DESC
            LIMIT %s;
        """,(symbol,interval,limit))
        rows=cur.fetchall()

    candles=[{
        "open_time":r[0],
        "open":r[1],
        "high":r[2],
        "low":r[3],
        "close":r[4],
        "volume":r[5],
        "quote_volume":r[6],
    } for r in rows]

    return list(reversed(candles))

def get_latest_order_book(conn,symbol:str)->Optional[Dict[str,Any]]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT spread_pct,total_bid_liquidity,total_ask_liquidity
            FROM raw_order_book_snapshots
            WHERE symbol=%s
            ORDER BY collected_at DESC
            LIMIT 1;
        """,(symbol,))
        row=cur.fetchone()

    if not row:
        return None

    return {
        "spread_pct":row[0],
        "total_bid_liquidity":row[1],
        "total_ask_liquidity":row[2],
    }

def calculate_relative_volume(candles:List[Dict[str,Any]])->Optional[Decimal]:
    if len(candles)<RELATIVE_VOLUME_LOOKBACK+1:
        return None

    current_volume=candles[-1]["quote_volume"]
    if current_volume is None:
        return None

    previous=candles[-(RELATIVE_VOLUME_LOOKBACK+1):-1]

    volumes=[c["quote_volume"] for c in previous if c["quote_volume"] is not None]
    if not volumes:
        return None

    avg=sum(volumes)/Decimal(len(volumes))
    if avg==0:
        return None

    return current_volume/avg

def calculate_features_for_symbol(ticker,c15,c1h,ob)->Optional[Dict[str,Any]]:
    symbol=ticker["symbol"]

    if len(c15)<21 or len(c1h)<21:
        return None

    pc15=pct_change(c15[-1]["close"],c15[-4]["close"])
    pc1h=pct_change(c1h[-1]["close"],c1h[-3]["close"])

    rv15=calculate_relative_volume(c15)
    rv1h=calculate_relative_volume(c1h)

    price=ticker["price"]
    high=ticker["high_price"]
    low=ticker["low_price"]

    d_high=None
    d_low=None

    if high and high!=0:
        d_high=((price-high)/high)*Decimal("100")

    if low and low!=0:
        d_low=((price-low)/low)*Decimal("100")

    spread=ob["spread_pct"] if ob else None
    slippage=spread

    liquidity=False
    if ob and spread is not None:
        liquidity=(
            spread>0
            and spread<=Decimal("4")
            and slippage is not None
            and slippage<=Decimal("6")
            and ob["total_bid_liquidity"] is not None
            and ob["total_ask_liquidity"] is not None
            and ob["total_bid_liquidity"]>Decimal("1000")
            and ob["total_ask_liquidity"]>Decimal("1000")
        )

    mom15=pc15 is not None and pc15>0
    mom1h=pc1h is not None and pc1h>0

    last4=c15[-4:]
    min4=min(c["low"] for c in last4)

    mom_recovery=(
        pc1h is not None and pc1h<0
        and pc15 is not None and pc15>0
        and price>min4
    )

    drop_change=pct_change(c1h[-1]["close"],c1h[-3]["close"])
    drop_active=False if drop_change is None else drop_change<STRONG_DROP_PCT

    pump=False
    if len(c1h)>=5:
        p=pct_change(c1h[-1]["close"],c1h[-5]["close"])
        if p is not None:
            pump=p>EXTREME_PUMP_PCT

    return{
        "token_id":ticker["token_id"],
        "symbol":symbol,
        "price_change_15m_pct":pc15,
        "price_change_1h_pct":pc1h,
        "price_change_24h_pct":ticker["price_change_24h_pct"],
        "relative_volume_15m":rv15,
        "relative_volume_1h":rv1h,
        "distance_to_24h_high_pct":d_high,
        "distance_to_24h_low_pct":d_low,
        "spread_pct":spread,
        "estimated_slippage_pct":slippage,
        "liquidity_gate_passed":liquidity,
        "momentum_15m_positive":mom15,
        "momentum_1h_positive":mom1h,
        "momentum_1h_recovering":mom_recovery,
        "strong_drop_active":drop_active,
        "extreme_pump_recent":pump,
    }

def save_feature(conn,f):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO features (
                token_id,symbol,
                price_change_15m_pct,price_change_1h_pct,price_change_24h_pct,
                relative_volume_15m,relative_volume_1h,
                distance_to_24h_high_pct,distance_to_24h_low_pct,
                spread_pct,estimated_slippage_pct,
                liquidity_gate_passed,
                momentum_15m_positive,momentum_1h_positive,momentum_1h_recovering,
                strong_drop_active,extreme_pump_recent
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);
        """,(
            f["token_id"],f["symbol"],
            f["price_change_15m_pct"],f["price_change_1h_pct"],f["price_change_24h_pct"],
            f["relative_volume_15m"],f["relative_volume_1h"],
            f["distance_to_24h_high_pct"],f["distance_to_24h_low_pct"],
            f["spread_pct"],f["estimated_slippage_pct"],
            f["liquidity_gate_passed"],
            f["momentum_15m_positive"],f["momentum_1h_positive"],f["momentum_1h_recovering"],
            f["strong_drop_active"],f["extreme_pump_recent"]
        ))

def main():
    conn=psycopg2.connect(**DB_CONFIG)
    try:
        tickers=get_latest_tickers(conn)
        print(f"Candidatos: {len(tickers)}")

        with conn:
            for t in tickers:
                c15=get_candles(conn,t["symbol"],"15m",30)
                c1h=get_candles(conn,t["symbol"],"1h",30)
                ob=get_latest_order_book(conn,t["symbol"])

                f=calculate_features_for_symbol(t,c15,c1h,ob)
                if not f:
                    continue

                save_feature(conn,f)

                print(f"{t['symbol']} RV15={f['relative_volume_15m']} RV1H={f['relative_volume_1h']} Spread={f['spread_pct']} LG={f['liquidity_gate_passed']}")

    finally:
        conn.close()

if __name__=="__main__":
    main()