from math import log1p
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


def safe_log_volume(value: Any) -> float:
    """
    Usa log1p para evitar que volúmenes relativos gigantes dominen todo.

    Ejemplo:
      RV=2  -> 1.09
      RV=38 -> 3.66
      RV=81 -> 4.40
    """
    numeric_value = max(to_float(value), 0.0)
    return log1p(numeric_value)


# -------------------------------------------------------------------
# SCORE PRINCIPAL
# -------------------------------------------------------------------

def score_signal(feature: Dict[str, Any]) -> float:
    """
    Calcula un score de ranking para priorizar señales.

    Importante:
    - No define si algo es señal o no.
    - No cambia las reglas del experimento v0.
    - Solo sirve para ordenar señales ya detectadas.
    """

    rv15 = to_float(feature.get("relative_volume_15m"))
    rv1h = to_float(feature.get("relative_volume_1h"))
    momentum15 = to_float(feature.get("price_change_15m_pct"))
    momentum1h = to_float(feature.get("price_change_1h_pct"))
    spread = to_float(feature.get("spread_pct"), default=999.0)
    liquidity_ok = feature.get("liquidity_gate_passed")

    # -----------------------------
    # FILTROS DUROS
    # -----------------------------
    if not liquidity_ok:
        return 0.0

    if spread <= 0 or spread > 4:
        return 0.0

    # -----------------------------
    # NORMALIZACIÓN DE VOLUMEN
    # -----------------------------
    rv15_score = safe_log_volume(rv15)
    rv1h_score = safe_log_volume(rv1h)

    # -----------------------------
    # MOMENTUM NORMALIZADO
    # -----------------------------
    momentum15_score = max(momentum15, 0.0) / 5.0
    momentum1h_score = max(momentum1h, 0.0) / 5.0

    # -----------------------------
    # SCORE BASE
    # -----------------------------
    score = (
        rv15_score * 0.50 +
        rv1h_score * 0.25 +
        momentum15_score * 0.15 +
        momentum1h_score * 0.10
    )

    # -----------------------------
    # BONUS DE COHERENCIA
    # -----------------------------
    if rv15 > 2 and momentum15 > 1:
        score *= 1.15

    # -----------------------------
    # PENALIZACIÓN POR SPREAD
    # -----------------------------
    if spread > 2:
        score *= 0.50
    elif spread > 1:
        score *= 0.80

    return round(score, 6)


def explain_score(feature: Dict[str, Any]) -> Dict[str, Any]:
    """
    Devuelve el detalle del score para debug y análisis.
    """

    rv15 = to_float(feature.get("relative_volume_15m"))
    rv1h = to_float(feature.get("relative_volume_1h"))
    momentum15 = to_float(feature.get("price_change_15m_pct"))
    momentum1h = to_float(feature.get("price_change_1h_pct"))
    spread = to_float(feature.get("spread_pct"), default=999.0)
    liquidity_ok = feature.get("liquidity_gate_passed")

    rv15_score = safe_log_volume(rv15)
    rv1h_score = safe_log_volume(rv1h)

    momentum15_score = max(momentum15, 0.0) / 5.0
    momentum1h_score = max(momentum1h, 0.0) / 5.0

    base_score = (
        rv15_score * 0.50 +
        rv1h_score * 0.25 +
        momentum15_score * 0.15 +
        momentum1h_score * 0.10
    )

    penalty = 1.0
    invalid_reason = None

    if not liquidity_ok:
        penalty = 0.0
        invalid_reason = "liquidity_gate_failed"
    elif spread <= 0:
        penalty = 0.0
        invalid_reason = "invalid_spread"
    elif spread > 4:
        penalty = 0.0
        invalid_reason = "spread_above_limit"
    elif spread > 2:
        penalty = 0.50
    elif spread > 1:
        penalty = 0.80

    bonus = 1.0

    if rv15 > 2 and momentum15 > 1:
        bonus = 1.15

    final_score = base_score * bonus * penalty

    return {
        "score": round(final_score, 6),
        "base_score": round(base_score, 6),
        "bonus": bonus,
        "penalty": penalty,
        "invalid_reason": invalid_reason,
        "rv15_raw": rv15,
        "rv1h_raw": rv1h,
        "rv15_score": round(rv15_score, 6),
        "rv1h_score": round(rv1h_score, 6),
        "momentum15_raw": momentum15,
        "momentum1h_raw": momentum1h,
        "momentum15_score": round(momentum15_score, 6),
        "momentum1h_score": round(momentum1h_score, 6),
        "spread": spread,
        "liquidity_ok": liquidity_ok,
    }


# -------------------------------------------------------------------
# RANKING
# -------------------------------------------------------------------

def rank_signals(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Recibe una lista de señales/features en formato dict
    y devuelve la misma lista ordenada de mayor a menor ranking_score.
    """

    ranked = []

    for signal in signals:
        signal_copy = dict(signal)
        score_detail = explain_score(signal_copy)

        signal_copy["ranking_score"] = score_detail["score"]
        signal_copy["score_detail"] = score_detail

        ranked.append(signal_copy)

    ranked.sort(
        key=lambda item: (
            item.get("ranking_score", 0),
            1 if item.get("signal_level") == "high" else 0,
        ),
        reverse=True,
    )

    return ranked


# -------------------------------------------------------------------
# DATA ACCESS
# -------------------------------------------------------------------

def get_signals_with_features(statuses=None) -> List[Dict[str, Any]]:
    """
    Trae señales con sus features asociadas.

    Por defecto trae señales open y executed para poder auditar ranking.
    Cuando se integre con paper_trader, podremos usar solo status='open'.
    """

    if statuses is None:
        statuses = ["open", "executed"]

    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    s.id AS signal_id,
                    s.symbol,
                    COALESCE(t.name, 'N/A') AS token_name,
                    s.signal_level,
                    s.status,
                    s.price_at_signal,
                    s.allocation_pct,
                    s.created_at,

                    f.price_change_15m_pct,
                    f.price_change_1h_pct,
                    f.price_change_24h_pct,
                    f.relative_volume_15m,
                    f.relative_volume_1h,
                    f.spread_pct,
                    f.liquidity_gate_passed
                FROM signals s
                LEFT JOIN features f
                    ON f.id = s.feature_id
                LEFT JOIN raw_tokens t
                    ON t.id = s.token_id
                WHERE s.status = ANY(%s)
                ORDER BY s.created_at DESC;
                """,
                (statuses,),
            )

            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

            return [dict(zip(columns, row)) for row in rows]

    finally:
        conn.close()


def get_open_signals_with_features() -> List[Dict[str, Any]]:
    return get_signals_with_features(statuses=["open"])


# -------------------------------------------------------------------
# REPORT
# -------------------------------------------------------------------

def print_ranked_signals(signals: List[Dict[str, Any]]) -> None:
    ranked = rank_signals(signals)

    print("\nRANKING DE SEÑALES")
    print("-" * 180)

    if not ranked:
        print("No hay señales para rankear.")
        print("-" * 180)
        return

    for index, signal in enumerate(ranked, start=1):
        detail = signal["score_detail"]

        print(
            f"{index:02d}. "
            f"{signal.get('symbol', 'N/A'):14} | "
            f"{str(signal.get('token_name', 'N/A'))[:18]:18} | "
            f"level={signal.get('signal_level', 'N/A'):6} | "
            f"status={signal.get('status', 'N/A'):10} | "
            f"score={signal.get('ranking_score', 0):8.6f} | "
            f"price={signal.get('price_at_signal')} | "
            f"24h={signal.get('price_change_24h_pct')}% | "
            f"15m={signal.get('price_change_15m_pct')}% | "
            f"1h={signal.get('price_change_1h_pct')}% | "
            f"RV15={signal.get('relative_volume_15m')} | "
            f"RV1H={signal.get('relative_volume_1h')} | "
            f"Spread={signal.get('spread_pct')}% | "
            f"LQ={signal.get('liquidity_gate_passed')}"
        )

        print(
            f"    detalle: "
            f"base={detail['base_score']} | "
            f"bonus={detail['bonus']} | "
            f"penalty={detail['penalty']} | "
            f"invalid={detail['invalid_reason']} | "
            f"rv15_log={detail['rv15_score']} | "
            f"rv1h_log={detail['rv1h_score']} | "
            f"mom15_norm={detail['momentum15_score']} | "
            f"mom1h_norm={detail['momentum1h_score']}"
        )

    print("-" * 180)


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------

def main():
    """
    Ejecutable para revisar ranking desde consola.

    Por defecto muestra open + executed para auditar también las señales
    que ya fueron tomadas por paper_trader.
    """

    signals = get_signals_with_features(statuses=["open", "executed"])
    print_ranked_signals(signals)


if __name__ == "__main__":
    main()