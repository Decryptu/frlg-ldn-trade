"""Append-only, local daily ledger for supervised Mystery Gift attempts."""

import csv
from datetime import datetime
from pathlib import Path


CSV_HEADER = ("attempt", "received_result", "time", "trainer_name", "trainer_ot")


def daily_attempt_path(directory, *, now=None):
    """Return the local-date CSV path without creating it."""
    now = now or datetime.now().astimezone()
    return Path(directory) / f"mystery-gift-attempts-{now:%Y-%m-%d}.csv"


def append_attempt(directory, *, received_result, trainer=None, now=None):
    """Append one attempt and return ``(path, attempt_number)``.

    ``trainer`` is a parsed LinkPlayer when the console reached that stage. Its
    low 16-bit trainer ID is rendered as a five-digit decimal value for the
    human-facing `trainer_ot` CSV column. Early failed joins have blank
    identity columns but remain auditable attempts.
    """
    if type(received_result) is not bool:
        raise ValueError("received_result must be a bool")
    now = now or datetime.now().astimezone()
    path = daily_attempt_path(directory, now=now)
    path.parent.mkdir(parents=True, exist_ok=True)

    exists = path.exists()
    attempt_number = 1
    if exists:
        with path.open("r", encoding="utf-8", newline="") as current:
            # A normal ledger has one header plus N attempts, so its physical
            # row count is the next attempt number. Treat a manually-created
            # empty file as a fresh ledger rather than emitting attempt zero.
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
