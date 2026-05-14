import subprocess
import sys


STEPS = [
    {
        "name": "Actualizar candidatos, velas y order books",
        "command": ["python", "collector/candidate_refresh_collector.py"],
    },
    {
        "name": "Limpiar features previas",
        "command": [
            "docker",
            "exec",
            "-i",
            "alpha_momentum_postgres",
            "psql",
            "-U",
            "alpha_user",
            "-d",
            "alpha_momentum",
            "-c",
            "TRUNCATE TABLE features CASCADE;",
        ],
    },
    {
        "name": "Calcular features",
        "command": ["python", "strategies/features_calculator.py"],
    },
    {
        "name": "Generar señales",
        "command": ["python", "strategies/signal_generator.py"],
    },
    {
        "name": "Mostrar watchlist",
        "command": ["python", "strategies/watchlist_report.py"],
    },
]


def run_step(step_name: str, command: list[str]) -> None:
    print("\n" + "=" * 100)
    print(f"PASO: {step_name}")
    print("=" * 100)

    result = subprocess.run(command)

    if result.returncode != 0:
        print(f"\nERROR en paso: {step_name}")
        print(f"Comando fallido: {' '.join(command)}")
        sys.exit(result.returncode)


def main() -> None:
    print("Iniciando ciclo Alpha Momentum Predictor...")

    for step in STEPS:
        run_step(step["name"], step["command"])

    print("\n" + "=" * 100)
    print("CICLO FINALIZADO")
    print("=" * 100)


if __name__ == "__main__":
    main()