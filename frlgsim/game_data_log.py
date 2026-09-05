"""The ledger for what the console tells us about itself, session after session.

Every Mystery Gift session ships a `MysteryGiftLinkGameData` before anything else happens: the
player's name and trainer id, the version, the flag id of the card they hold, the four Poke Mart
questionnaire words, their six Easy Chat battle words, and the counters `WonderCardMetadata` keeps
for that card - battles won, battles lost, trades, stamps [decomp:src/mystery_gift.c:361].
`mg_script.parse_link_game_data` has always read it and the host has always printed it, which
means it was read once and then lost with the log.

Two things want it kept instead:

- **The counters only mean something as a difference.** "3 battles won" is a number; "3 where the
  last session said 2, and the card is the same one" is the observation that the console really
  does maintain the stats a Battle Count Card would be built on [docs/mystery_gift_untried.md].
  One session cannot show that. `changes` is the whole point of the file.
- **The word ids are the only French vocabulary the console volunteers.** Anything the player has
  typed comes back as a slot id; when `easychat_french` cannot render one, that id is worth one
  question to the player and becomes ground truth for every gift after it.

The record carries the raw 0x64 bytes as hex, so a later question can be answered by re-parsing an
old session rather than by spending a new one.
"""

import json
from datetime import datetime
from pathlib import Path

from . import easychat, easychat_french, mg_script


def _words(values):
    return [int(value) & 0xFFFF for value in values]


def record(data, *, tag=None, now=None):
    """-> a JSON-shaped dict for one console's `MysteryGiftLinkGameData`."""
    now = now or datetime.now().astimezone()
    return {
        "time": now.isoformat(timespec="seconds"),
        "tag": tag,
        "player_name": data.player_name,
        # None rather than a wrong number: a full 7-character name overwrites the first byte of
        # playerTrainerId in the struct the console sends [LinkGameData.trainer_id_is_reliable].
        "trainer_id": (data.trainer_id & 0xFFFF) if data.trainer_id_is_reliable else None,
        "version": data.version_name,
        "game_code": data.game_code.decode("ascii", "replace"),
        "software_version": data.software_version,
        "flag_id": data.flag_id,
        "icon_species": data.metadata_icon_species,
        "battles_won": data.battles_won,
        "battles_lost": data.battles_lost,
        "num_trades": data.num_trades,
        "num_stamps": len(data.stamps),
        "max_stamps": data.max_stamps,
        "stamps": [list(stamp) for stamp in data.stamps],
        "questionnaire": _words(data.questionnaire_words),
        "easy_chat_profile": _words(data.easy_chat_profile),
        "raw": data.raw.hex(),
    }


def append(path, data, *, tag=None, now=None):
    """Add one session to the ledger. -> (Path, the record written)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = record(data, tag=tag, now=now)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path, entry


def read(path):
    """-> every record in the ledger, oldest first. A truncated last line is ignored: the host is
    killed with a signal often enough that a half-written line is an ordinary way for one to end."""
    entries = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return tuple(entries)


def parse_raw(entry):
    """-> the record's bytes back through `parse_link_game_data`, for a question asked later."""
    return mg_script.parse_link_game_data(bytes.fromhex(entry["raw"]))


def console_key(entry):
    """Which console a record came from. The trainer id is absent for a 7-character name, so the
    name and the cartridge are what identify it."""
    return (entry.get("player_name"), entry.get("game_code"), entry.get("version"))


_COUNTERS = (
    ("battles_won", "battles won"),
    ("battles_lost", "battles lost"),
    ("num_trades", "trades"),
    ("num_stamps", "stamps"),
)


def changes(before, after):
    """-> what moved between two records of the same console, as lines.

    A counter that moves while the flag id is unchanged is the console maintaining the stats for a
    card it kept; a counter that moves across a card change says nothing, and is reported with the
    card change beside it so it cannot be read as the first thing.
    """
    lines = []
    if before.get("flag_id") != after.get("flag_id"):
        lines.append(f"card flagId {before.get('flag_id')} -> {after.get('flag_id')}")
    for key, name in _COUNTERS:
        old, new = before.get(key), after.get(key)
        if old != new:
            lines.append(f"{name} {old} -> {new}")
    if before.get("max_stamps") != after.get("max_stamps"):
        lines.append(f"max stamps {before.get('max_stamps')} -> {after.get('max_stamps')}")
    for key, name in (("questionnaire", "questionnaire"),
                      ("easy_chat_profile", "Easy Chat battle profile")):
        old, new = before.get(key), after.get(key)
        if old != new:
            lines.append(f"{name} {easychat.describe_words(old or ())} "
                         f"-> {easychat.describe_words(new or ())}")
    return tuple(lines)


def unknown_words(entry):
    """-> the word ids in this record that no French console has been seen to render.

    These are the ones a single question to the player converts into ground truth, and they cost
    nothing to collect: the console sends them whether or not anything reads them.
    """
    words = tuple(entry.get("questionnaire") or ()) + tuple(entry.get("easy_chat_profile") or ())
    return easychat_french.check(w for w in words if w)


def _describe_words(values):
    # Word 0 is EC_GROUP_POKEMON_2 index 0, which the console rejects and prints as "???"
    # [IsECWordInvalid, decomp:src/easy_chat.c:118]: an all-zero profile is empty, not six words.
    values = [value for value in values or () if value not in (0, easychat.UNDEFINED)]
    if not values:
        return "(none)"
    rendered = easychat_french.render(values)
    return f"{rendered} [{easychat.describe_words(values)}]"


def summary(entries):
    """-> the ledger read back as lines: one block per console, and what changed between its
    sessions. Sessions that changed nothing are counted, not printed."""
    lines = []
    consoles = {}
    for entry in entries:
        consoles.setdefault(console_key(entry), []).append(entry)
    for key, records in consoles.items():
        name, game_code, version = key
        latest = records[-1]
        trainer = ("TID unavailable (7-character name)" if latest.get("trainer_id") is None
                   else f"TID {latest['trainer_id']}")
        lines.append(f"{name!r} ({trainer}) on {version} [{game_code}]: "
                     f"{len(records)} session(s), {records[0]['time']} .. {latest['time']}")
        lines.append(f"  card flagId {latest['flag_id']}, {latest['battles_won']} battles won, "
                     f"{latest['battles_lost']} lost, {latest['num_trades']} trades, "
                     f"{latest['num_stamps']}/{latest['max_stamps']} stamps")
        lines.append(f"  questionnaire: {_describe_words(latest.get('questionnaire'))}")
        lines.append(f"  battle profile: {_describe_words(latest.get('easy_chat_profile'))}")
        quiet = 0
        for before, after in zip(records, records[1:]):
            moved = changes(before, after)
            if not moved:
                quiet += 1
                continue
            tag = after.get("tag") or after["time"]
            lines.append(f"  {tag}: " + "; ".join(moved))
        if quiet:
            lines.append(f"  ({quiet} session(s) changed nothing)")
        unknown = unknown_words(latest)
        if unknown:
            lines.append("  never seen rendered in French, worth one question to the player: "
                         + ", ".join(easychat.describe_word(value) for value in unknown))
    return lines
