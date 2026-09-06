import csv
from datetime import datetime
from pathlib import Path


CSV_HEADER = ("attempt", "received_result", "time", "trainer_name", "trainer_ot")


def daily_attempt_path(directory, *, now=None):
    now = now or datetime.now().astimezone()
    return Path(directory) / f"mystery-gift-attempts-{now:%Y-%m-%d}.csv"


def append_attempt(directory, *, received_result, trainer=None, now=None):
    """``trainer_ot`` is the low 16 bits of the trainer ID as five decimal digits; a failed early join
    leaves both identity columns blank."""
    if type(received_result) is not bool:
        raise ValueError("received_result must be a bool")
    now = now or datetime.now().astimezone()
    path = daily_attempt_path(directory, now=now)
    path.parent.mkdir(parents=True, exist_ok=True)

    exists = path.exists()
    attempt_number = 1
    if exists:
        with path.open("r", encoding="utf-8", newline="") as current:
            attempt_number = max(1, sum(1 for _ in csv.reader(current)))

    trainer_name = "" if trainer is None else trainer.name
    trainer_ot = "" if trainer is None else f"{trainer.trainer_id & 0xFFFF:05d}"
    with path.open("a", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        if not exists:
            writer.writerow(CSV_HEADER)
        writer.writerow((
            attempt_number,
            "true" if received_result else "false",
            now.strftime("%H:%M"),
            trainer_name,
            trainer_ot,
        ))
    return path, attempt_number
