import subprocess
import time
from datetime import datetime
from pathlib import Path


INTERVAL_SECONDS = 1200  # 20 minutos
LOG_FILE = Path("logs/monitor_loop.log")


def write_log(text: str):
    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(text + "\n")


def run_command(command: str) -> str:
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True
    )

    output = result.stdout.strip()

    if result.stderr:
        output += "\n" + result.stderr.strip()

    return output


def run_monitor_cycle():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    header = f"\n{'=' * 100}\nMONITOR CYCLE — {now}\n{'=' * 100}"
    print(header)
    write_log(header)

    commands = [
        ("Actualizar precios", "python collector/open_trades_ticker_collector.py"),
        ("Evaluar trades", "python simulator/trade_evaluator.py"),
    ]

    for name, command in commands:
        section = f"\n--- {name} ---"
        print(section)
        write_log(section)

        output = run_command(command)

        print(output)
        write_log(output)

    footer = f"\nPróximo monitoreo en {INTERVAL_SECONDS // 60} minutos..."
    print(footer)
    write_log(footer)


def main():
    print("Monitor automático iniciado.")
    print("No cierres esta terminal si querés que siga corriendo.")
    print("Para detenerlo: CTRL + C")

    while True:
        run_monitor_cycle()
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
