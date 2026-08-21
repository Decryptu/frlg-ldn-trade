# JoySpot discovery: tested surface and blocker record

This document preserves the completed research into whether FireRed can discover this project through
**Mystery Gift → Wonder Cards → Wireless Communication**. The shipping distributor uses the
hardware-proven **Wonder Cards → Friend** path instead.

**Verdict: blocked.** 21 controlled advertisements across three stages produced no reaction under
Wireless Communication, while the Friend positive control was listed in every stage. The Switch LDN
bridge (Sloop) synthesizes `gRfuLinkStatus->partner[].serialNo` itself, and nothing observable in the
LDN advertisement changes it.

---

## 1. What FireRed requires

`Task_CardOrNewsOverWireless` (`src/union_room.c:2415`) scans, waits 120 frames, then evaluates
candidate slot 0 and associates with no button press. The gates, **in this order**:

1. `Rfu_GetWonderDistributorPlayerData` (`src/link_rfu_3.c:917`) populates the candidate **only** if
   `partner[idx].serialNo == RFU_SERIAL_WONDER_DISTRIBUTOR (0x7F7D)`; otherwise it zeroes the entry.
   This runs inside the *listen* task.
2. `groupScheduledAnim == UNION_ROOM_SPAWN_IN && !startedActivity`.
3. `HasWonderCardOrNewsByLinkGroup` — the advertised `hasCard` bit; failing it plays **SE_BOO**.
4. `CreateTask_RfuReconnectWithParent(...)`.

Because gate 1 zeroes the entry, gates 2–4 are unreachable while the serial is wrong, and no SE_BOO
is produced. Uniform silence is the exact signature of gate 1 failing.

## 2. Measured conclusions

**Sloop reports `serialNo == 0x0002` (`RFU_SERIAL_GAME`).** Derivation, from the sweep results alone:

- `sAcceptedSerialNos` (`src/link_rfu_2.c:240`) is `{0x0002, 0x7F7D}`. The Friend list only shows a
  candidate whose serial passes `IsRfuSerialNumberValid`; otherwise `Rfu_GetCompatiblePlayerData`
  zeroes the gname and the activity filter drops it. The control was listed in all three stages
  (and in stage 1.1 it also completed an LDN join) ⇒ **serial ∈ {0x0002, 0x7F7D}**.
- Wireless Communication was silent for all 21 wireless candidates ⇒ **serial ≠ 0x7F7D**.
- Therefore the synthesized value is exactly `0x0002`.

**The advertisement record carries no serial field.** A real FRLG host always sets serial `0x0002`,
yet in the captured native advertisement every byte outside the four known fields is zero:

```
50 10 | c1 cc bf bf c8 ff 00 00 | 65 ac | 00 00 00 00 | 84 15 | 00 00 00 00 00 00
TID   | uname                   | parent| UNEXPLAINED | search| UNEXPLAINED
```

If Sloop carried a serial in the 24-byte record, `02 00` (or `00 02`) would appear in one of those
regions. It does not. Consistent with `svc_47` (`src/sloopsvc.c:34`), whose parameter block is
`{u8 HostRfuGameData[0x10]; u8 HostRfuUsername[8]}` — 24 bytes, no serial field — while the candidate
list is written by the bridge through `svc_45_rfu_link_status()`.

**Positive result: the record model is correct.** `0x1584 & 0x7F = 4 = ACTIVITY_TRADE` in the native
capture, and activity 21 at the same offset got us listed under Friend and completed an LDN join. The
search word at `record[16:18]` decomposes as
`activity:7 | bit7 | version:3 | language:3 | hasCard?:1 | startedActivity:1`
(version 5 = LeafGreen, language 2 = English in the capture). Everything except the serial works.

## 3. Tested surface

Every row is one controlled advertisement, held live until the operator answered. `auth` counts
802.11 authentication attempts observed in the JSONL trace — the console never attempted association
for any wireless candidate.

| Stage | Candidate | Record on the air | Pia appVer | auth |
|---|---|---|---|---|
| 1.0 | `baseline` | `2288 bfc7 cfff ffff ffff bef1 0000 0000 8415 0000 0000 0000` | 88 | 0 |
| 1.0 | `scene_0` | `2288 bfc7 cfff ffff ffff 82f1 0000 0000 8415 0000 0000 0000` | 88 | 0 |
| 1.0 | `scene_21` | `2288 bfc7 cfff ffff ffff c1f1 0000 0000 8415 0000 0000 0000` | 88 | 0 |
| 1.0 | `scene_7f7d` | `2288 bfc7 cfff ffff ffff 0bf1 0000 0000 8415 0000 0000 0000` | 88 | 0 |
| 1.0 | `app_version_7f7d` | `2288 bfc7 cfff ffff ffff e3f1 0000 0000 8415 0000 0000 0000` | 88 | 0 |
| 1.0 | `pia_app_version_7f7d` | `2288 bfc7 cfff ffff ffff 8cf1 0000 0000 8415 0000 0000 0000` | 32637 | 0 |
| 1.0 | `record_word_12` | `2288 bfc7 cfff ffff ffff faf1 7d7f 0000 8415 0000 0000 0000` | 88 | 0 |
| 1.0 | `record_word_14` | `2288 bfc7 cfff ffff ffff e7f1 0000 7d7f 8415 0000 0000 0000` | 88 | 0 |
| 1.0 | `record_word_18` | `2288 bfc7 cfff ffff ffff ecf1 0000 0000 8415 7d7f 0000 0000` | 88 | 0 |
| 1.0 | `record_word_20` | `2288 bfc7 cfff ffff ffff 73f1 0000 0000 8415 0000 7d7f 0000` | 88 | 0 |
| 1.0 | `record_word_22` | `2288 bfc7 cfff ffff ffff f4f1 0000 0000 8415 0000 0000 7d7f` | 88 | 0 |
| 1.0 | `friend_control` | `2288 bfc7 cfff ffff ffff b4f1 0000 0000 9515 0000 0000 0000` | 88 | **1 (listed + joined)** |
| 1.1 | `wireless_activity21_no_card` | `2288 bfc7 cfff ffff ffff 7cf1 0000 0000 9515 0000 0000 0000` | 88 | 0 |
| 1.1 | `wireless_activity21_card` | `2288 bfc7 cfff ffff ffff eff1 0000 0000 9555 0000 0000 0000` | 88 | 0 |
| 1.1 | `wireless_activity4_card` | `2288 bfc7 cfff ffff ffff c4f1 0000 0000 8455 0000 0000 0000` | 88 | 0 |
| 1.1 | `wireless_activity0_card` | `2288 bfc7 cfff ffff ffff 20f1 0000 0000 8055 0000 0000 0000` | 88 | 0 |
| 1.1 | `friend_control` | `2288 bfc7 cfff ffff ffff 24f1 0000 0000 9515 0000 0000 0000` | 88 | **1 (listed + joined)** |
| 1.2 | `serial_be_12` | `2288 bfc7 cfff ffff ffff e6f1 7f7d 0000 9555 0000 0000 0000` | 88 | 0 |
| 1.2 | `serial_be_14` | `2288 bfc7 cfff ffff ffff acf1 0000 7f7d 9555 0000 0000 0000` | 88 | 0 |
| 1.2 | `serial_be_18` | `2288 bfc7 cfff ffff ffff 93f1 0000 0000 9555 7f7d 0000 0000` | 88 | 0 |
| 1.2 | `serial_be_20` | `2288 bfc7 cfff ffff ffff 83f1 0000 0000 9555 0000 7f7d 0000` | 88 | 0 |
| 1.2 | `serial_be_22` | `2288 bfc7 cfff ffff ffff 86f1 0000 0000 9555 0000 0000 7f7d` | 88 | 0 |
| 1.2 | `serial_le_13` | `2288 bfc7 cfff ffff ffff e3f1 007d 7f00 9555 0000 0000 0000` | 88 | 0 |
| 1.2 | `serial_le_19` | `2288 bfc7 cfff ffff ffff d3f1 0000 0000 9555 007d 7f00 0000` | 88 | 0 |
| 1.2 | `search_bit7_clear` | `2288 bfc7 cfff ffff ffff bbf1 0000 0000 1515 0000 0000 0000` | 88 | 0 |
| 1.2 | `friend_control` | `2288 bfc7 cfff ffff ffff d8f1 0000 0000 9515 0000 0000 0000` | 88 | 0 (listed; join not attempted) |

Constant across every row: `local_communication_id = 0x01006fa0233f8000`, LDN version 4, channel 1,
`max_participants = 2`, Pia `sysCommVer = 22`, and scene `22287` except where the row varies it.

Raw traces: `joyspot_1.{0,1,2}_sweep*.jsonl` and `.log`.

### Note on stage 1.1

Its four candidates varied `activity` and the `hasCard` hypothesis — both of which FireRed reads
*after* the serial gate. They could not have differed from one another, and four identical silences
was the only possible outcome. The run is still evidence (it confirms gate ordering on hardware) but
it tested variables downstream of the failure.

## 4. Deliberately not tested, and why

- **`local_communication_id`** — the console's scan almost certainly filters on it, so a different
  value makes us invisible, which is indistinguishable from the serial gate failing. No informative
  negative is possible.
- **Blind scene-ID brute force** — 65,536 values; forbidden by the plan. The Friend control already
  proves scene `22287` is acceptable for Mystery Gift discovery generally, so scene is not the
  discriminator.
- **Multi-variable combinations** — only worth exploring once a single variable produces a reaction.

## 5. What would reopen this

1. Direct evidence from the Sloop bridge itself showing a rule that assigns `partner[].serialNo`
   from anything advertisable.
2. A real NSO-era Wonder Card distribution existing (which would prove the bridge implements the
   distributor serial). The evidence runs the other way: Nintendo shipped the Mystic and Aurora
   Tickets on Switch as a Hall-of-Fame grant rather than a distribution event.
3. A capture of any LDN advertisement that a Switch itself treats as a wonder distributor.

## 6. Impact

This blocks only the zero-button Wireless Communication/JoySpot experience. The Friend path uses
the same post-connection Mystery Gift conversation and is hardware-proven end to end. Reopen this
research only if new evidence identifies a Switch-LDN field that controls the synthesized RFU serial.
