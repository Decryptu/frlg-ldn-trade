"""Daily Mystery Gift attempt-ledger coverage."""

import csv
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from frlgsim import linkplayer, mystery_gift_attempts


def test_attempt_ledger_uses_daily_csv_and_preserves_client_identity():
    moment = datetime(2026, 8, 27, 15, 23, tzinfo=timezone.utc)
    trainer = linkplayer.LinkPlayer(name="RED", trainer_id=1267)
    with TemporaryDirectory() as directory:
        path, number = mystery_gift_attempts.append_attempt(
            directory, received_result=True, trainer=trainer, now=moment)
        assert path == Path(directory) / "mystery-gift-attempts-2026-08-27.csv"
        assert number == 1
        path2, number2 = mystery_gift_attempts.append_attempt(
            directory, received_result=False, trainer=None,
            now=moment.replace(minute=33))
        assert path2 == path and number2 == 2
        with path.open(newline="", encoding="utf-8") as source:
            rows = list(csv.reader(source))
    assert rows == [
        ["attempt", "received_result", "time", "trainer_name", "trainer_ot"],
        ["1", "true", "15:23", "RED", "01267"],
        ["2", "false", "15:33", "", ""],
    ]
