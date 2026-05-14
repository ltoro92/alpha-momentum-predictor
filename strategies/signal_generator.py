import json
from decimal import Decimal
from typing import Any, Dict, List

import psycopg2


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}


MEDIUM_RV_15M = Decimal("2.0")
MEDIUM_RV_1H = Decimal("1.5")
MEDIUM_MAX_SPREAD = Decimal("4")
MEDIUM_MAX_SLIPPAGE = Decimal("6")
MEDIUM_ALLOCATION_PCT = Decimal("25")

HIGH_RV_15M = Decimal("4.0")
HIGH_RV_1H = Decimal("2.5")
HIGH_MAX_SPREAD = Decimal("2")
HIGH_MAX_SLIPPAGE = Decimal("3")
HIGH_ALLOCATION_PCT = Decimal("50")

STOP_LOSS_PCT = Decimal("-10")
TP1_PCT = Decimal("20")
TP2_PCT = Decimal("35")
TP3_PCT = Decimal("50")


def pct_price(price: Decimal, pct: Decimal) -> Decimal:
    return price * (Decimal("1") + (pct / Decimal("100")))


def get_latest_features(conn) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (f.symbol)
                f.id,
                f.token_id,
                f.symbol,
                f.price_change_15m_pct,
                f.price_change_1h_pct,
                f.price_change_24h_pct,
                f.relative_volume_15m,
                f.relative_volume_1h,
                f.spread_pct,
                f.estimated_slippage_pct,
                f.liquidity_gate_passed,
                f.momentum_15m_positive,
                f.momentum_1h_positive,
                f.momentum_1h_recovering,
                f.strong_drop_active,
                f.extreme_pump_recent,
                t.price
            FROM features f
            JOIN (
                SELECT DISTINCT ON (symbol)
                    symbol,
                    price,
                    collected_at
                FROM raw_tickers_24h
                ORDER BY symbol, collected_at DESC
            ) t ON t.symbol = f.symbol
            ORDER BY f.symbol, f.calculated_at DESC;
            """
        )

        rows = cur.fetchall()

    return [
        {
            "feature_id": row[0],
            "token_id": row[1],
            "symbol": row[2],
            "price_change_15m_pct": row[3],
            "price_change_1h_pct": row[4],
            "price_change_24h_pct": row[5],
            "relative_volume_15m": row[6],
            "relative_volume_1h": row[7],
            "spread_pct": row[8],
            "estimated_slippage_pct": row[9],
            "liquidity_gate_passed": row[10],
            "momentum_15m_positive": row[11],
            "momentum_1h_positive": row[12],
            "momentum_1h_recovering": row[13],
            "strong_drop_active": row[14],
            "extreme_pump_recent": row[15],
            "price": row[16],
        }
        for row in rows
    ]


def already_has_recent_signal(conn, symbol: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM signals
            WHERE symbol = %s
            AND created_at >= NOW() - INTERVAL '4 hours'
            LIMIT 1;
            """,
            (symbol,),
        )

        return cur.fetchone() is not None


def classify_signal(feature: Dict[str, Any]) -> Dict[str, Any]:
    reasons = []

    required_checks = {
        "liquidity_gate_passed": feature["liquidity_gate_passed"] is True,
        "momentum_15m_positive": feature["momentum_15m_positive"] is True,
        "momentum_1h_positive_or_recovering": (
            feature["momentum_1h_positive"] is True
            or feature["momentum_1h_recovering"] is True
        ),
        "relative_volume_15m_medium": (
            feature["relative_volume_15m"] is not None
            and feature["relative_volume_15m"] >= MEDIUM_RV_15M
        ),
        "relative_volume_1h_medium": (
            feature["relative_volume_1h"] is not None
            and feature["relative_volume_1h"] >= MEDIUM_RV_1H
        ),
        "spread_medium": (
            feature["spread_pct"] is not None
            and feature["spread_pct"] <= MEDIUM_MAX_SPREAD
        ),
        "slippage_medium": (
            feature["estimated_slippage_pct"] is not None
            and feature["estimated_slippage_pct"] <= MEDIUM_MAX_SLIPPAGE
        ),
        "no_strong_drop": feature["strong_drop_active"] is False,
        "no_extreme_pump": feature["extreme_pump_recent"] is False,
    }

    failed = [name for name, passed in required_checks.items() if not passed]

    if failed:
        return {
            "has_signal": False,
            "signal_level": None,
            "allocation_pct": Decimal("0"),
            "reason": {
                "result": "no_signal",
                "failed_checks": failed,
                "checks": required_checks,
            },
        }

    high_checks = {
        "relative_volume_15m_high": feature["relative_volume_15m"] >= HIGH_RV_15M,
        "relative_volume_1h_high": feature["relative_volume_1h"] >= HIGH_RV_1H,
        "spread_high": feature["spread_pct"] <= HIGH_MAX_SPREAD,
        "slippage_high": feature["estimated_slippage_pct"] <= HIGH_MAX_SLIPPAGE,
        "momentum_1h_positive": feature["momentum_1h_positive"] is True,
    }

    high_failed = [name for name, passed in high_checks.items() if not passed]

    if not high_failed:
        return {
            "has_signal": True,
            "signal_level": "high",
            "allocation_pct": HIGH_ALLOCATION_PCT,
            "reason": {
                "result": "signal",
                "signal_level": "high",
                "checks": required_checks,
                "high_checks": high_checks,
            },
        }

    return {
        "has_signal": True,
        "signal_level": "medium",
        "allocation_pct": MEDIUM_ALLOCATION_PCT,
        "reason": {
            "result": "signal",
            "signal_level": "medium",
            "checks": required_checks,
            "high_checks": high_checks,
            "high_failed_checks": high_failed,
        },
    }


def save_signal(conn, feature: Dict[str, Any], classification: Dict[str, Any]) -> None:
    price = feature["price"]

    stop_price = pct_price(price, STOP_LOSS_PCT)
    tp1_price = pct_price(price, TP1_PCT)
    tp2_price = pct_price(price, TP2_PCT)
    tp3_price = pct_price(price, TP3_PCT)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO signals (
                token_id,
                feature_id,
                symbol,
                signal_level,
                status,
                price_at_signal,
                realistic_entry_price,
                stop_price,
                tp1_price,
                tp2_price,
                tp3_price,
                allocation_pct,
                reason,
                created_at
            )
            VALUES (
                %s, %s, %s, %s, 'open',
                %s, %s, %s, %s, %s, %s, %s, %s,
                NOW()
            );
            """,
            (
                feature["token_id"],
                feature["feature_id"],
                feature["symbol"],
                classification["signal_level"],
                price,
                price,
                stop_price,
                tp1_price,
                tp2_price,
                tp3_price,
                classification["allocation_pct"],
                json.dumps(classification["reason"], default=str),
            ),
        )


def main() -> None:
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        features = get_latest_features(conn)

        print(f"Features evaluadas: {len(features)}")

        signals_created = 0
        no_signal = 0
        duplicates = 0

        with conn:
            for feature in features:
                symbol = feature["symbol"]

                classification = classify_signal(feature)

                if not classification["has_signal"]:
                    no_signal += 1
                    continue

                if already_has_recent_signal(conn, symbol):
                    duplicates += 1
                    print(f"[DUPLICATE] {symbol}: ya tiene señal reciente")
                    continue

                save_signal(conn, feature, classification)
                signals_created += 1

                print(
                    f"[SIGNAL] {symbol} | "
                    f"level={classification['signal_level']} | "
                    f"allocation={classification['allocation_pct']}% | "
                    f"price={feature['price']} | "
                    f"RV15={feature['relative_volume_15m']} | "
                    f"RV1H={feature['relative_volume_1h']} | "
                    f"spread={feature['spread_pct']}"
                )

        print("Proceso terminado.")
        print(f"Señales creadas: {signals_created}")
        print(f"Sin señal: {no_signal}")
        print(f"Duplicadas: {duplicates}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()