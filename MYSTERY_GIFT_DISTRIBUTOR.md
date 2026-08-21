# FireRed Mystery Gift Distributor

Hand a real Switch FireRed/LeafGreen save a Wonder Card + delivery RAM script over LDN. The default
card awards one level-50 Celebi from the deliveryman on the second floor of any Pokémon Center. It
does not include an item unless the host is started with `--item ID`.

**Status: hardware-proven end to end.** The Friend-path distributor has completed discovery,
connection, LinkPlayer exchange, card transfer, save/reboot persistence, and deliveryman execution
on a Switch. The delivery script remains available after use for later conversations.

```
sudo -E ./.venv/bin/python -u frlgmg_host.py --live
```

The hardware-proven command for this machine is:

```bash
sudo -E ./.venv/bin/python -u frlgmg_host.py --live \
  --phy phy3 --skip-encryption --native-nonce-sequence --session-response-first
```

`phy3` is specific to this MT7601U host; choose an AP-capable PHY elsewhere.

Then on the Switch: **Mystery Gift → Wonder Cards → Friend**, pick the host from the list.

Companion docs: [docs/joyspot_discovery_findings.md](docs/joyspot_discovery_findings.md) (why the
Wireless Communication path is not reachable) and
[docs/frlgtrade_host_design.md](docs/frlgtrade_host_design.md).

---

## 1. Which discovery path, and why

FireRed can be handed a Wonder Card two ways. Both reach the **same** gift conversation.

| | Friend | Wireless Communication (JoySpot) |
|---|---|---|
| listener | `Task_ListenForCompatiblePartners` [union_room.c:3757] | `Task_ListenForWonderDistributor` [union_room.c:3799] |
| accepts RFU serial | `IsRfuSerialNumberValid` → `{0x0002, 0x7F7D}` | `== 0x7F7D` only [link_rfu_3.c:920] |
| selection | player picks from a list | auto-connects, no button press |
| reachable from a Switch | **yes** | **no** |

Both menus run the identical `InitializeRfuLinkManager_JoinGroup()` scan and then converge on the
same `MysteryGiftClient_Create()` [mystery_gift_menu.c:1231]; `sourceIsFriend` selects only *how you
connect*. The Switch's LDN bridge reports every peer's `serialNo` as `0x0002` — the value is written
by the emulator after our beacon has already been received, and `svc_47`'s parameter block carries no
serial field at all [sloopsvc.c:9]. 21 controlled advertisements confirmed it. Full derivation and
the tested surface: [docs/joyspot_discovery_findings.md](docs/joyspot_discovery_findings.md).

So the distributor ships on the Friend path. Nothing about the gift is reduced by that — only the
zero-button auto-connect is lost.

## 2. What the console does after it joins

The console does not decide the flow; **we** do. Its Mystery Gift client boots with a
two-instruction script [mystery_gift_scripts.c:15]:

```c
{CLI_RECV, MG_LINKID_CLIENT_SCRIPT}
{CLI_COPY_RECV}
```

It connects, asks us for instructions, and then executes whatever `MysteryGiftClientCmd` array we
send [mystery_gift_client.c:87]. That is why a Linux host can drive flows a real cartridge cannot:
FireRed only carries two server scripts in ROM, but the client understands the whole opcode set.

Session shape:

```
console joins  →  SEND_PLAYER_IDS  →  LinkPlayer block exchange  →  one standby barrier
                                                                          ↓
  server → CLIENT_SCRIPT (sClientScript_SendGameData, 32 B)
  client → GAME_DATA     (MysteryGiftLinkGameData, 96 B)   ── validated, card flag compared
  server → CLIENT_SCRIPT (sClientScript_SaveCard, 48 B)
  server → CARD          (struct WonderCard, 332 B)
  server → RAM_SCRIPT    (1024 B: the delivery bytecode, zero-padded)
  client → READY_END     (1024 B)
                                                                          ↓
                                          close-link handshake  →  disconnect
```

The common LDN/Pia/Reliable/RFU stack is shared with the trade host and hardware-proven. The
LinkPlayer ordering is Mystery-Gift-specific: the host issues one block request, waits for the
Switch's valid block, then sends its own block and waits for the standby barrier.

## 3. Modules

| file | role |
|---|---|
| `frlgsim/mg_link.py` | MysteryGiftLink framing: 6-byte `{ident, crc, size}` header block + ≤252-byte chunks |
| `frlgsim/mg_script.py` | client-script assembler, the decomp's canned scripts, `MysteryGiftLinkGameData` reader |
| `frlgsim/mg_server.py` | server-script interpreter (`SVR_*`), transcribing `gMysteryGiftServerScript_SendWonderCard` |
| `frlgsim/host_mystery_gift.py` | the leader activity engine: `tick()` → parent gSendCmd, `feed_child_slot()` ← child row |
| `frlgsim/host_mg_app.py` | run configuration + application, subclassing the trade host's proven runtime |
| `frlgmg_host.py` | CLI |
| `frlgsim/wonder_card.py` | the payload: 332-byte card + Celebi `givemon`/`setmonmove`/`setflag`/`end` delivery script; `giveitem` is optional |

`HostSession` now takes an `engine=` keyword, so the LDN/Pia/Reliable/RFU stack is shared verbatim
with the trade host and only the activity above it differs.

## 4. Two things that are easy to get wrong

**Size 0 means 1024, not empty.** `MysteryGiftLink_InitSend` [mystery_gift_link.c:55] expands a zero
size to `MG_LINK_BUFFER_SIZE`. `SVR_COPY_SAVED_RAM_SCRIPT` never sets `ramScriptSize`
[mystery_gift_server.c:275], so the RAM script goes out as a full 1024-byte message — as does
`CLI_SEND_READY_END`. The CRC covers the padded buffer, not the meaningful prefix.

**Block pacing has no acknowledgement.** `SEND_BLOCK_INIT` is *silently ignored* unless the
receiver's slot is `RECV_STATE_READY` [link_rfu_2.c:1146], and the slot only returns to READY when
the console's `MGL_ResetReceived` runs. Nothing on the wire reports that, and the sender's own flow
control does not help: `MGL_Send` waits on `MGL_HasReceived(sendPlayerId)`, which for the parent is
its own slot 0, and `Rfu_SetBlockReceivedFlag` [link_rfu_2.c:1044] sets the parent's own flag
immediately — the four-VBlank `numBlocksReceived` countdown [link_rfu_2.c:1220] applies only to
blocks arriving *from a child*. A native parent therefore paces blocks about a frame apart and just
relies on the console keeping up. `MysteryGiftTiming.inter_block_gap_frames` (12) buys far more:
measured against the console model, the console may take 13 frames to consume a block with nothing
dropped and 16 before the transfer dies. Lose that race and the console waits forever for a block
that was dropped without an error.

## 5. Tests

```
./.venv/bin/python tests/test_mystery_gift_flow.py          # framing, scripts, server, engine
./.venv/bin/python tests/test_mystery_gift_host_wiring.py   # advertisement, config, session seam
./.venv/bin/python tests/test_mystery_gift_offline.py       # payload + CRC foundations
```

`tests/test_mystery_gift_flow.py` models the RFU block-receive gate, `MGL_Receive`, and
one-command-per-frame client-script execution. `tests/test_mystery_gift_end_to_end.py` adds an
impaired Reliable/RFU path and a native-shaped ID16/ID17 framing fixture. These remain offline
regressions; a completed Switch Friend-path run is the hardware evidence for the shipping flow.

## 6. Not built

* **Stamp relay.** `CLI_SAVE_STAMP` writes only `cardMetadata.stampData` [mystery_gift.c:307] and
  never touches the card, so a stamp-only client script adds stamps without the card wipe that
  `CLI_SAVE_CARD` causes. Constraint worth designing around: `IsStampInMetadata` [mystery_gift.c:272]
  rejects a stamp whose id **or** species collides with an existing one, so every station in a relay
  needs both unique. Max 7.
* **Wonder News**, stamps, e-Reader trainers, `CLI_RUN_MEVENT_SCRIPT` gifts (direct Pokémon),
  `CLI_RUN_BUFFER_SCRIPT`.
* **Serving consoles back to back** without restarting the host.
