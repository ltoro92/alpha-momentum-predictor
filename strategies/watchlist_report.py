import psycopg2


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "alpha_momentum",
    "user": "alpha_user",
    "password": "alpha_password",
}


def main() -> None:
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    f.symbol,
                    v.display_symbol,
                    v.display_name,
                    f.price_change_24h_pct,
                    f.price_change_15m_pct,
                    f.price_change_1h_pct,
                    f.relative_volume_15m,
                    f.relative_volume_1h,
                    f.spread_pct,
                    f.liquidity_gate_passed,
                    f.momentum_15m_positive,
                    f.momentum_1h_positive,
                    f.momentum_1h_recovering,
                    f.strong_drop_active,
                    f.extreme_pump_recent,
                    CASE
                        WHEN f.liquidity_gate_passed = true
                         AND f.momentum_15m_positive = true
                         AND (f.momentum_1h_positive = true OR f.momentum_1h_recovering = true)
                         AND f.strong_drop_active = false
                         AND f.extreme_pump_recent = false
                         AND f.relative_volume_15m >= 2.0
                         AND f.relative_volume_1h >= 1.5
                        THEN 'SIGNAL_READY'

                        WHEN f.liquidity_gate_passed = true
                         AND f.momentum_15m_positive = true
                         AND (f.momentum_1h_positive = true OR f.momentum_1h_recovering = true)
                         AND f.strong_drop_active = false
                         AND f.extreme_pump_recent = false
                         AND f.relative_volume_15m >= 2.0
                        THEN 'WATCHLIST_NEEDS_1H_VOLUME'

                        WHEN f.liquidity_gate_passed = true
                         AND f.momentum_15m_positive = true
                         AND (f.momentum_1h_positive = true OR f.momentum_1h_recovering = true)
                         AND f.strong_drop_active = false
                         AND f.extreme_pump_recent = false
                        THEN 'WATCHLIST_MOMENTUM_OK'

                        ELSE 'NO_SETUP'
                    END AS setup_status
                FROM features f
                JOIN v_tradeable_tokens v
                    ON v.trading_symbol = f.symbol
                ORDER BY
                    CASE
                        WHEN f.liquidity_gate_passed = true
                         AND f.momentum_15m_positive = true
                         AND (f.momentum_1h_positive = true OR f.momentum_1h_recovering = true)
                         AND f.relative_volume_15m >= 2.0
                        THEN 1
                        ELSE 2
                    END,
                    f.relative_volume_1h DESC,
                    f.relative_volume_15m DESC
                LIMIT 30;
                """
            )

            rows = cur.fetchall()

            print("\nTOP WATCHLIST")
            print("-" * 180)

            for row in rows:
                (
                    symbol,
                    display_symbol,
                    display_name,
                    change_24h,
                    change_15m,
                    change_1h,
                    rv15,
                    rv1h,
                    spread,
                    liquidity_ok,
                    mom15,
                    mom1h,
                    mom1h_rec,
                    strong_drop,
                    extreme_pump,
                    setup_status,
                ) = row

                print(
                    f"{setup_status:28} | "
                    f"{display_symbol:16} | "
                    f"{symbol:14} | "
                    f"24h={change_24h:>9}% | "
                    f"15m={change_15m:>9}% | "
                    f"1h={change_1h:>9}% | "
                    f"RV15={rv15} | "
                    f"RV1H={rv1h} | "
                    f"Spread={spread}% | "
                    f"LQ={liquidity_ok}"
                )

    finally:
        conn.close()


if __name__ == "__main__":
    main()