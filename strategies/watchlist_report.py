import sys
from decimal import Decimal
from typing import Any, Dict, List

import psycopg2


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}


# -------------------------------------------------------------------
# HELPERS
# -------------------------------------------------------------------

def to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default

    if isinstance(value, Decimal):
        return float(value)

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_decimal(value: Any, decimals: int = 8) -> str:
    if value is None:
        return "N/A"

    try:
        number = to_float(value)
        return f"{number:.{decimals}f}"
    except Exception:
        return str(value)


# -------------------------------------------------------------------
# SETUP CLASSIFICATION
# -------------------------------------------------------------------

def classify_setup(row: Dict[str, Any]) -> str:
    """
    Clasifica una feature para reporte.

    Importante:
    Esto NO abre trades.
    Esto NO cambia reglas de señal.
    Solo ordena visualmente el watchlist.
    """

    momentum_15m = to_float(row.get("price_change_15m_pct"))
    momentum_1h = to_float(row.get("price_change_1h_pct"))
    momentum_24h = to_float(row.get("price_change_24h_pct"))
    rv15 = to_float(row.get("relative_volume_15m"))
    rv1h = to_float(row.get("relative_volume_1h"))
    spread = to_float(row.get("spread_pct"), default=999.0)
    liquidity_ok = row.get("liquidity_gate_passed")

    if not liquidity_ok:
        return "NO_SETUP"

    if spread <= 0 or spread > 4:
        return "NO_SETUP"

    # Observación extrema: no es señal operable v0.
    # Sirve para casos tipo ZEST: queremos verlos, no necesariamente tradearlos.
    if momentum_24h > 100:
        return "EXTREME_PUMP_OBSERVATION"

    # Regla visual alineada con signal_generator v0.
    if (
        momentum_15m > 0
        and rv15 >= 2
        and rv1h >= 1.5
        and -10 <= momentum_24h <= 25
    ):
        return "SIGNAL_READY"

    if (
        momentum_15m > 0
        and momentum_1h > 0
        and rv15 >= 2
        and rv1h < 1.5
    ):
        return "WATCHLIST_NEEDS_1H_VOLUME"

    if (
        momentum_15m > 0
        and momentum_1h > 0
        and rv1h >= 1.5
    ):
        return "WATCHLIST_MOMENTUM_OK"

    return "NO_SETUP"


def setup_priority(setup_status: str) -> int:
    priorities = {
        "SIGNAL_READY": 1,
        "EXTREME_PUMP_OBSERVATION": 2,
        "WATCHLIST_NEEDS_1H_VOLUME": 3,
        "WATCHLIST_MOMENTUM_OK": 4,
        "NO_SETUP": 5,
    }

    return priorities.get(setup_status, 99)


# -------------------------------------------------------------------
# DATA ACCESS
# -------------------------------------------------------------------

def get_latest_features(limit: int = 40) -> List[Dict[str, Any]]:
    """
    Trae solo la última feature por símbolo.

    Esto evita que el watchlist mezcle datos históricos con datos actuales.
    """

    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH latest_features AS (
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
                        f.liquidity_gate_passed,
                        f.calculated_at
                    FROM features f
                    ORDER BY f.symbol, f.calculated_at DESC
                ),
                latest_tokens AS (
                    SELECT DISTINCT ON (rt.symbol)
                        rt.id,
                        rt.symbol,
                        rt.name,
                        rt.raw_payload,
                        rt.last_seen_at
                    FROM raw_tokens rt
                    ORDER BY rt.symbol, rt.last_seen_at DESC NULLS LAST
                )
                SELECT
                    lf.id,
                    lf.token_id,
                    lf.symbol,

                    COALESCE(
                        NULLIF(lt.raw_payload->>'symbol', ''),
                        NULLIF(lt.name, ''),
                        lf.symbol
                    ) AS display_symbol,

                    COALESCE(
                        NULLIF(lt.name, ''),
                        NULLIF(lt.raw_payload->>'name', ''),
                        lf.symbol
                    ) AS token_name,

                    lf.price_change_15m_pct,
                    lf.price_change_1h_pct,
                    lf.price_change_24h_pct,
                    lf.relative_volume_15m,
                    lf.relative_volume_1h,
                    lf.spread_pct,
                    lf.liquidity_gate_passed,
                    lf.calculated_at
                FROM latest_features lf
                LEFT JOIN latest_tokens lt
                    ON lt.symbol = lf.symbol
                ORDER BY lf.calculated_at DESC
                LIMIT %s;
                """,
                (limit,),
            )

            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

            return [dict(zip(columns, row)) for row in rows]

    finally:
        conn.close()


# -------------------------------------------------------------------
# REPORT
# -------------------------------------------------------------------

def print_watchlist(rows: List[Dict[str, Any]]) -> None:
    enriched_rows = []

    for row in rows:
        row_copy = dict(row)
        row_copy["setup_status"] = classify_setup(row_copy)
        row_copy["setup_priority"] = setup_priority(row_copy["setup_status"])
        enriched_rows.append(row_copy)

    enriched_rows.sort(
        key=lambda item: (
            item["setup_priority"],
            -to_float(item.get("relative_volume_15m")),
            -to_float(item.get("relative_volume_1h")),
            -to_float(item.get("price_change_15m_pct")),
        )
    )

    print("\nTOP WATCHLIST")
    print("-" * 180)

    if not enriched_rows:
        print("No hay features disponibles para mostrar.")
        print("-" * 180)
        return

    for row in enriched_rows:
        setup_status = row.get("setup_status", "N/A")
        display_symbol = row.get("display_symbol") or "N/A"
        symbol = row.get("symbol") or "N/A"

        price_change_24h = format_decimal(row.get("price_change_24h_pct"))
        price_change_15m = format_decimal(row.get("price_change_15m_pct"))
        price_change_1h = format_decimal(row.get("price_change_1h_pct"))
        rv15 = format_decimal(row.get("relative_volume_15m"))
        rv1h = format_decimal(row.get("relative_volume_1h"))
        spread = format_decimal(row.get("spread_pct"))
        liquidity_ok = row.get("liquidity_gate_passed")
        calculated_at = row.get("calculated_at")

        print(
            f"{setup_status:28} | "
            f"{str(display_symbol)[:16]:16} | "
            f"{symbol:14} | "
            f"24h={price_change_24h}% | "
            f"15m={price_change_15m}% | "
            f"1h={price_change_1h}% | "
            f"RV15={rv15} | "
            f"RV1H={rv1h} | "
            f"Spread={spread}% | "
            f"LQ={liquidity_ok} | "
            f"calc={calculated_at}"
        )

    print("-" * 180)


def main() -> None:
    rows = get_latest_features(limit=50)
    print_watchlist(rows)


if __name__ == "__main__":
    main()