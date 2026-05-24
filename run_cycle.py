import subprocess
import sys


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


STEPS = [
    {
        "name": "Actualizar candidatos, velas y order books",
        "command": ["python", "collector/candidate_refresh_collector.py"],
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


def run_step(step):
    print("\n" + "=" * 100)
    print(f"PASO: {step['name']}")
    print("=" * 100)

    result = subprocess.run(
        step["command"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        print(f"\nERROR en paso: {step['name']}")
        print(f"Comando fallido: {' '.join(step['command'])}")
        sys.exit(result.returncode)


def main():
    print("Iniciando ciclo Alpha Momentum Predictor...")

    for step in STEPS:
        run_step(step)

    print("\n" + "=" * 100)
    print("CICLO FINALIZADO")
    print("=" * 100)


if __name__ == "__main__":
    main()