import subprocess
import sys


def run_step(name, command):
    print("\n" + "=" * 100)
    print(f"PASO: {name}")
    print("=" * 100)

    result = subprocess.run(command, shell=True)

    if result.returncode != 0:
        print(f"\n[ERROR] Falló el paso: {name}")
        sys.exit(result.returncode)


def main():
    run_step(
        "Actualizar precios de trades abiertos",
        "python collector/open_trades_ticker_collector.py"
    )

    run_step(
        "Evaluar trades abiertos",
        "python simulator/trade_evaluator.py"
    )

    print("\n" + "=" * 100)
    print("MONITOREO FINALIZADO")
    print("=" * 100)


if __name__ == "__main__":
    main()