import subprocess
import time
import sys
from datetime import datetime
from pathlib import Path



try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


INTERVAL_SECONDS = 1200  # 20 minutos
LOG_FILE = Path("logs/experiment_loop.log")


def write_log(text: str):
    LOG_FILE.parent.mkdir(exist_ok=True)

    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(text + "\n")


def run_command(command: str) -> int:
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    output_parts = []

    if result.stdout:
        output_parts.append(result.stdout.strip())

    if result.stderr:
        output_parts.append(result.stderr.strip())

    output = "\n".join(output_parts)

    if output:
        print(output)
        write_log(output)

    return result.returncode

    output = result.stdout.strip()

    if result.stderr:
        output += "\n" + result.stderr.strip()

    if output:
        print(output)
        write_log(output)

    return result.returncode


def run_step(name: str, command: str) -> bool:
    section = f"\n{'=' * 100}\nPASO: {name}\n{'=' * 100}"
    print(section)
    write_log(section)

    return_code = run_command(command)

    if return_code != 0:
        error_message = f"[ERROR] Falló el paso: {name} | return_code={return_code}"
        print(error_message)
        write_log(error_message)
        return False

    return True


def run_experiment_cycle():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    header = f"\n{'#' * 100}\nEXPERIMENT CYCLE — {now}\n{'#' * 100}"
    print(header)
    write_log(header)

    steps = [
        (
            "Actualizar mercado, calcular features y generar señales",
            "python run_cycle.py"
        ),
        (
            "Abrir trades simulados si hay cupo",
            "python simulator/paper_trader.py"
        ),
        (
            "Actualizar y evaluar trades abiertos",
            "python monitor_open_trades.py"
        ),
    ]

    for name, command in steps:
        ok = run_step(name, command)

        if not ok:
            warning = "Ciclo detenido por error. Se intentará nuevamente en el próximo intervalo."
            print(warning)
            write_log(warning)
            break

    footer = f"\nPróximo ciclo en {INTERVAL_SECONDS // 60} minutos..."
    print(footer)
    write_log(footer)


def main():
    print("Loop automático del experimento iniciado.")
    print("Este proceso corre run_cycle.py + paper_trader.py + monitor_open_trades.py.")
    print("No cierres esta terminal si querés que siga corriendo.")
    print("Para detenerlo: CTRL + C")

    while True:
        run_experiment_cycle()
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()