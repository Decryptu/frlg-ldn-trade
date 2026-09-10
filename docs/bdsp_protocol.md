---
title: The game protocol
parent: Brilliant Diamond and Shining Pearl
nav_order: 2
---

# BDSP's own protocol, and controlling a character

Inside the Pia payloads BDSP runs a typed protocol of its own. It does not have to be guessed:
`TeamLumi/opendpr` is a decompiled C# recreation of the game, and `Dpr.NetworkUtils.NetDataParser`
lists every message it speaks. Each is an `ANetData<T>` with a one-byte `DataID`, and each `T` is a
plain struct.

## Framing

    0x0  1  data id
    0x1  2  payload length, BIG-endian
    0x3  .  the struct, little-endian, as C# lays it out

**The layout is packed.** `JoinData` is `byte, byte, byte, short, Vector3`: seventeen bytes packed,
twenty with C#'s default alignment, because an aligned `short` would sit at offset 4 rather than 3.
The console's own message is seventeen bytes and its length field says `0x0011`. Every payload in
every capture agrees with the packed reading.

`NetDataParser` registers **65** messages and `pokeldn/bdsp/netdata.py` holds all of them, generated
from an `opendpr` checkout by `scripts/gen_bdsp_netdata.py`. 53 have a layout the source decides; the
other twelve carry a C# string, an array or a list and are listed in `netdata.OPAQUE`, because the
source does not decide their layout.

The binary does. A payload is the **marshalled** struct: `ANetData<T>.ConvertStructToBytes`
[main.bin 0x27bb0e0] goes through `Marshal.SizeOf`, `Marshal.AllocHGlobal` and
`Marshal.StructureToPtr`, so a string and an array become fixed-size fields rather than references,
and the size of every struct is its `native_size` in the executable's `Il2CppTypeDefinitionSizes`
table (`MetadataRegistration.typeDefinitionsSizes`, one entry per type definition). A string's
character count is in `global-metadata.dat`'s `fieldMarshaledSizes`; an array's count is derived by
subtracting the other fields from the native size. Every struct is packed, and the four payloads a
capture holds match the layout read this way byte for byte. `scratchpad/bdsp_native_layout.py`
prints them; `room.NATIVE_SIZES` holds the twelve sizes.

| id | payload | bytes | layout |
|---|---|---|---|
| 0x02 | `PosListData` | 72 | 12 x `PosData` (ushort posX, ushort posZ, short rotY) |
| 0x13 | `TradePokeData` | 328 | one encrypted PB8 at stored size |
| 0x14 | `NetRecodeData` | 694 | `RECORD` 120, `RANDOM_SEED` 132, `TvRecodeData` 204, 4 x `TV_STR_DATA` 36, `RECORD_HEAD` 48, ten ints, six bytes |
| 0x15 | `BallDecoData` | 143 | affixSealCount, Is3DEditMode, IsAppliedTemplate, then `AttachSealData` 140 (20 x `SealParam{short x, y, z; byte id}`) |
| 0x18, 0x54 | `UgSecretBase` | 616 | short zoneID, posX, posY; byte direction, expansionStatus; int goodCount; 30 x `UgStoneStatue` 20; bool isEnable (4) |
| 0x22 | `StanbyListData` | 20 | 5 x `StandbyData` (isAddPlayer, hostIndex, myIndex, langId) |
| 0x24 | `TradeTranerData` | 32 | 13 UTF-16 chars, uint tranerId, byte cassetVersion, byte langId |
| 0x29, 0x61 | `UgStationID_to_DigFossilIDList` | 8 | 8 bytes of dig-fossil ids |
| 0x38 | `BattleMatchingPokeData` | 481 | a 328-byte PB8, 20 x `SealParam` 7, uint attachPokemonId, uint attachPersonalRnd, byte index, num, is3DEditMode, isAppliedTemplate, affixSealCount |
| 0x42 | `NetPlayerName` | 28 | 13 UTF-16 chars, byte genderid, byte languageId |

`BattleMatchingPokeData` holds two arrays, so its 328 is taken from `TradePokeData` and the 20 seals
from `AttachSealData`; the two together are the only split of 468 that matches both. The four
measured layouts are also in `room.MEASURED`.

`StandbyData` is four bytes, `isAddPlayer, hostIndex, myIndex, langId`, and the sender allocates
five of them [1.3.0 main 0x01e52fa0, `UnionRoomManager$$SendStandbyPlayerData`], filling slot *i*
from the *i*-th entry of its match-wait list (`UnionStateController.unionMatchWaitDataList`) with
`isAddPlayer = 1` and `hostIndex` left 0. A console standing in the room with an empty list answers
twenty zero bytes.

A station puts itself on that list with `NetDataStandbyWaitData` (0x59), the same four bytes:
`59 0004 01 00 01 03` from station 1 with language 3 (French) is accepted by
`UnionStateController$$ReciveMatchWaitData` [1.3.0 main 0x01e539b0], which takes the station's name
from `NetworkManager.GetGamerData(myIndex)`, and the next answer to a 0x22 request is
`22 0014 01 00 01 03` followed by sixteen zero bytes. `isAddPlayer = 0` takes the removal branch.
Nothing changed on the console's screen when the record was added.

The marshaller does not clear what it allocates, so a fixed field carries heap residue past the
value it holds — ten bytes of it in `NetDataTradeTranerData`, on
[the trading page](bdsp_trade.md).

The ids are nibble-grouped — 0x01 to 0x09, 0x10 to 0x19, 0x20 to 0x29 and so on, no low nibble ever
reaching 0xA — so a gap in the numbering is the grouping rather than a missing message.

## What has been on the air

Four of the 65 appear in a capture of a console left alone in the room. The receiver drops
looped-back broadcasts before recording, so all of these are the console talking:

| id | class | reliable | unreliable | size | runs |
|---|---|---|---|---|---|
| 0x01 | `NetJoinData` | 2070 | 0 | 17 | 19 |
| 0x02 | `NetPosData` | 0 | 60 | 72 | 5 |
| 0x12 | `NetRequestData` | 4333 | 55 | 1 | 19 |
| 0x23 | `NetDataIsMatchWaitData` | 229 | 0 | 1 | 13 |

Two more come only when asked for (below): `NetDataBattleTypeData` (0x09), one byte, 0 on a console
with no battle set up, and `NetDataStandbyWaitListData` (0x22), twenty bytes. Two come when the
player picks the activity (the transitionType table below): `NetDataRecodeData` (0x14) and
`NetDataAttachSealNetData` (0x15). The trade messages are on [the trading page](bdsp_trade.md).

Every payload in the archive is a well-formed game message declaring a length that exactly accounts
for its bytes, over six thousand messages and nineteen runs.

`NetPosData` shows what a capture settles that the source cannot: its struct is an array, so it is one
of the twelve with no decidable layout, and yet 72 bytes is 12 points of 6 and nothing else divides.

## The messages the console repeats

**`NetJoinData`** is a player's arrival — the whole of `JoinData` and nothing else:

| offset | size | field |
|---|---|---|
| 0x00 | 1 | `avatarId`, 8 in every capture |
| 0x01 | 1 | `colorId`, 0 |
| 0x02 | 1 | `cassetVersion`, 0x31 |
| 0x03 | 2 | `InitRotY`, the facing in **degrees**, little-endian and unaligned |
| 0x05 | 12 | `InitPos`, three little-endian floats: x, y, z |

Four captures of four different places on the Union Room floor gave angles of 0, 90, 90 and 225 —
every one a multiple of 45, which is what an eight-direction facing is. `y` is 0.0 in three of them
and 1.5e-08 in the fourth, so it is a height on a flat room rather than a constant.

**`NetRequestData`** is one byte, `RequestDataID`, and names the message it wants;
`OpcManager._RequestNetDataCallback` is an `Action<byte>`. **`NetDataIsMatchWaitData`** is the console
answering its own request: `{isMatchWait = 0}`, "I am not waiting to be matched".

The console asks for two different things:

| asked for | times | in which runs |
|---|---|---|
| `NetDataIsMatchWaitData` (0x23) | 4333 | all nineteen |
| `NetCharacterStateData` (0x04) | 55 | four runs |

Those four are exactly the runs where an avatar appeared on the console's screen. Every run that sent
game messages and drew nothing asked for 0x04 zero times, across 265 sends, and in all four positive
runs the first 0x04 arrives after the client's first send. **When the game creates a character from a
join, it asks the station that sent it for that character's state**, so a request for 0x04 in the
capture is a second signal that a character exists — the screen having been the only trustworthy one.
`bin/bdsp_connect.py` prints it as a verdict.

The match-wait request stops being asked at t = 9.4 in every run that acknowledges the reliable
window, answered or not; the run that did not acknowledge it was asked 487 times in 75 seconds. It is
the acknowledgement that stops the asking.

**What a request can fetch.** The Union Room's receive handler, `UnionRoomManager$$SetNetData`
[1.3.0 main 0x01e50700], answers a `NetRequestData` for six ids and ignores every other:

| requested | the console sends | by |
|---|---|---|
| 0x01 `NetJoinData` | its join record | `UnionRoomManager$$SendJoinData` |
| 0x04 `NetCharacterStateData` | its character state | `UnionRoomManager$$SendOpcStateData` |
| 0x09 `NetDataBattleTypeData` | its battle rule | `UnionRoomManager$$SendBattleRuleData` |
| 0x13 `NetTradePokeData` | the Pokemon it is offering | `UnionRoomManager$$SendPokeData` |
| 0x22 `NetDataStandbyWaitListData` | its standby list | `UnionRoomManager$$SendStandbyPlayerData` |
| 0x23 `NetDataIsMatchWaitData` | whether it is waiting to be matched | `UnionRoomManager$$SendIsMatchWait` |

Sent one after another from a station whose character is in the room, five of the six are answered
on the reliable stream 30-130 ms after the request lands; 0x13 is not, because `SendPokeData` returns
without sending when no Pokemon is selected. The base game's handler [base main 0x01fd4600] answers
the same six ids, with 0x22 then named `NetDataTradeStandbyData`.

One 0x22 answer is the only message in the archive carrying the reliable header's zlib flag
(0x10): the 23 bytes of an all-zero list arrived as a 20-byte zlib stream (window 4 KB), and read raw
they parse as a `NetBonusStart` with an impossible length. The same message with one record filled
in, and the 20-byte join, arrived uncompressed. What decides the flag is unknown.
`bin/bdsp_connect.py` and `scratchpad/bdsp_opaque.py` inflate on the flag.

**Where the other opaque messages are spoken**, from the callers of each `ANetData<T>.SendReliableData`
in 1.3.0:

| id | class | sent by |
|---|---|---|
| 0x14 | `NetDataRecodeData` | `RecodeMatching$$SendRecodeData`, `UnionStateController$$SendRecodeData` |
| 0x15 | `NetDataAttachSealNetData` | `BallDecoMatching$$SendBallDecoData` |
| 0x18 | `NetSecretBaseData` | `UgNetworkManager$$SendMySecretBaseData`, and on request in `UgNetworkManager$$OnReceiveRequestData` |
| 0x29, 0x61 | the dig-fossil lists | `UgNetworkManager$$OnReceiveRequestData` |
| 0x38 | `NetDataBattleMatchingSelectPokemon` | `BattleMatchingManager$$SendSelectPokemonData` |
| 0x42 | `NetPlayerNameData` | `UgNetworkManager$$SendOnJoinNewPlayer`, `UgNetworkManager$$SendPlayerNameData` |
| 0x54 | `NetSecretBaseUpdate` | no reliable sender; `netdata.py` names it |

Three belong to Union Room activities other than trading (record mixing, ball capsules, a battle) and
the `Ug*` ones to the Grand Underground, where `NetPlayerNameData` is sent to a player who joins and
requests for the secret base and dig lists are answered. No Underground session has been captured.

**The stream decides the reply's stream.** All 4333 requests for `NetDataIsMatchWaitData` arrived on
the reliable protocol and all 55 for `NetCharacterStateData` on the unreliable one, with no crossover
in nineteen runs, and each is where the console puts its own answer.

The unreliable stream carries three messages and nothing else:

| bytes | times | message |
|---|---|---|
| `04 0002 00 00` | 853 | `NetCharacterStateData{state: NONE, isRecruiment: 0}`, every two seconds |
| `12 0001 04` | 55 | `NetRequestData` — "send me your `NetCharacterStateData`" |
| `02 0048 <72 B>` | 60 | `NetPosData`, twelve points, while the console's avatar walks |

`room.build_state()` produces the exact five bytes the console broadcasts and
`room.build_match_wait(False)` the exact four it answers itself with, so neither reply invents
anything.

## Sending messages the game acts on

**The reliable sequence id is shared with the console's own sends, and anything below the number its
acknowledgement names is discarded in silence.** One run's ack sat at 13, twenty messages went out
numbered 1 to 20, and exactly the eight from 13 up became avatars. Read the id fresh immediately
before each send.

**A join the transport acknowledges is not a join the game acts on.** Four runs sent exactly one join
each and all four were acknowledged on the first try; one produced a character and three produced
nothing. Fifteen joins in one run produced two characters, so a single join is roughly a one-in-eight
shot and a comparison cannot rest on one. `--room-pattern fixed` bursts them.

**One avatar appears per join message**, because `UnionOpcManager` calls `CreateCharacter(joinData)`
on each one. Forty joins are forty arrivals.

Avatars created this way **survive the scene**: the player walked out of the Union Room, down to the
Poke Center floor and into a shop, and the whole crowd came along, through the walls. Only restarting
the game cleared them. A remote player created without a session behind it is never cleaned up. A
character that has been *moved* is cleaned up when the station that moved it leaves the mesh.

## The character record

`OpcManager.CharaData` is
`{int stationIndex, string assetName, int colorId, int avatarId, int sexId, int cassetVersion}` and
`RemoveCharacter(int stationIndex)` takes the same key, so a character is keyed by the station it came
from.

### The model

`OpcManager.CreateCharaData(ANetData<JoinData>)` builds the record out of the join message, and
`avatarId` picks who appears:

    NetJoinData.avatarId  ->  CreateCharaData  ->  CharaData.avatarId
                          ->  UnionCharacterTable.SheetSheet1{ID, AssetName}
                          ->  OpLoadCharacter("persons/field/" + assetName)

`GetSexId(id)` and `GetNpcColorId(avatarId)` read the same value. `avatarId = 8` is a girl and 0 a boy
in a blue cap, with the sex changed as the binary predicts. `bin/bdsp_connect.py --join-avatar N`.

`NetDataTranerCardData` (0x05) is 75 blittable bytes whose first fields are `fashionId`, `bodyType`
and `genderid`, which reads like appearance and is not: `UnionOpcManager.CreateTranerCard()` builds
the trainer-card UI. Sending one is acknowledged and changes nothing on screen.

### The state byte

`StateData` is `{byte state, byte isRecruiment}`, and `state` is an `OpcState.OnlineState`:

| value | name | value | name |
|---|---|---|---|
| 0 | `NONE` | 5 | `RECRUITMENT_RECORD` |
| 1 | `DIG_FOSILL` | 6 | `RECRUITMENT_GREETINGS` |
| 2 | `SECRETBASE_ACTION` | 7 | `RECRUITMENT_BALL_DECORATION` |
| 3 | `RECRUITMENT_BATTLE` | 8 | `COMMUNICATE` |
| 4 | `RECRUITMENT_TRADE` | | |

`OpcController.ShowEmoticon(OnlineState)` and `GetEmoticonType(state)` read it, and the
`RECRUITMENT_*` values raise the speech bubble over a player advertising what they want. Answering
the console's standing request with `StateData{RECRUITMENT_TRADE, 1}` puts a trade bubble on a retail
console's screen.

Two earlier runs answered the same request with `StateData{NONE, 0}` and nothing happened. The
message, the stream and the bytes were all correct and the payload meant "I am doing nothing": a
negative result measured with a no-op payload is not a negative result.

### Walking

Over 80 of the console's own `NetPosData`: one message every 0.410 s spanning 0.935 units, which is
**2.28 units per second**. `room.POS_PERIOD` and `room.POS_STRIDE` are those numbers;
`--room-walk-stride` and `--room-walk-period` override them. Sending 0.1 units every 0.35 s — an
eighth of that — renders as a stutter: twelve points crossing a tiny distance, then a pause.

A walk has to be bounded. Sixty messages at the console's own speed is 55.8 units and crosses the
whole room: the character hits a wall, is pushed back by the game's own collision, keeps its facing
at the angle sent while the position moves, and leaves through the far wall. `--room-walk-steps 8`
stops inside the room. Two properties fall out: the game applies collision to a remote character's
movement, and it takes `rot_y` literally rather than deriving facing from the direction of travel.
The player has no collision against a remote character.

`PosData` is `{ushort posX, ushort posZ, short rotY}` with the game's own conversion
`pos = (-posX * 0.05, posZ * 0.05)` — a twentieth of a unit, with **x negated**. A captured trail
decodes to the same place its join message named.

## Being talked to

An emote **locks a player in place waiting to be interacted with**, so a console showing a trade
emote cannot start anything: someone has to walk up to it. The console broadcasts its own state, so
the moment the emote goes up is visible on the wire:

    NetCharacterStateData{state: 4, isRecruiment: 1}     the trade emote, up
    NetCharacterStateData{state: 0, isRecruiment: 0}     and down again

`isRecruiment` is the flag to gate on rather than "state is non-zero": state 18 is a console already
inside a trade, and approaching that is refused.

The approach is `NetDataTalkReserveData` (0x63), `63 00 01 00`, byte-for-byte what the console sends
when its own player walks up to someone. `bin/bdsp_connect.py --initiate-talk` sends it; it was
answered in 40 ms.

The exchange, with the client approaching:

    t=37.47  us  ->  64 0003 00 01 04   NetDataTalkReserveResultData{IsCanTalk, IsRecruitment, emoticonStateType}
    t=37.67  con ->  06 0005 00 01000000  NetDataTalkData{talkOpcSexId: 0, talkState: GREETING}
    t=80.68  con ->  10 0002 01 04      NetDataTalkCancelEndData{IsRecruitment: 1, emoticonStateType: 4}

**The talk is a request/response and the console blocks on the answer.** Unanswered, the player's own
character freezes until the game is rebooted. Answered with `NetDataTalkReserveResultData` (0x64), the
game runs its whole greeting: a greeting line, a name and an offer to trade, ending in "one second!"
while it waits. The player can leave that with B.

**`IsCanTalk` reads backwards from its name: 0 keeps the conversation alive, 1 makes the character
decline.** Four runs, one variable each:

| `IsCanTalk` | what followed | what the screen did |
|---|---|---|
| 0 | nothing | the greeting runs and parks on "one second!" |
| 1 | nothing | "sorry, I have other plans" and the chat closes |
| 1 | `NetDataSelectData{0}` | the same refusal |
| 1 | `NetDataSelectData{1}` | the same refusal |

The two runs that swept the select index were therefore refusing before the index could matter.

**A parked conversation is not reliably escapable.** B released the player in one run and did nothing
in another; killing the run — dropping the station — is the lever to try first and a reboot is the
fallback. Say so before a run that parks the talk.

### talkState, and the value that crashes the game

`TalkState` is `{CHECK = 0, GREETING = 1, NONE = 2}`, and the console is parked in `GREETING` waiting
to be advanced. `UnionStateController$$SwitchSpokenStateMine` is the handler and its whole shape is
one branch:

    0x1fd5e6c  cbz  w21, 0x1fd5e84    talkState == CHECK -> below
    0x1fd5e80  b    0x1fd85e0         anything else -> StartOpenGreetingMsgWindow

    0x1fd5e84  ldr  x0, [x0, #0x10]   systemController->msgWindow
    0x1fd5e88  cbz  x0, 0x1fd5f00     ... and when it is NULL:
    0x1fd5f00  mov  x19, xzr            x19 = 0
    0x1fd5ec0  ldr  x20, [x19, #0x10]   dereferences it. No guard anywhere.

CHECK is only meaningful to a console that already has a message window open. A player standing with
an emote up has none, so sending CHECK takes the game down — twice, before the handler was read.
GREETING takes the branch that opens the window. `pokeldn/bdsp/room.py` refuses to send CHECK at all.

**A state value read out of a sender is not safe to send until the receiver's handler has been
read.** CHECK really is what the initiator sends, in a state the console was not in.

The messages that advance a parked greeting are `NetDataSelectData{index}` (0x08) and
`NetDataTransitionData{transitionType, isRecruitment}` (0x07). Both are sent by the game as tail
calls, so a BL-only caller scan reports them as never sent; see
[finding callers](switch_re.md#finding-callers).

`transitionType` is an `OpcState.OnlineState`, and `UnionStateTransitionController$$SwitchTransition`
[1.3.0 main 0x01e5ba70] dispatches on it through a 19-entry table, the same activity reachable
under its `RECRUITMENT_*` value and its `NOW_*` value:

| transitionType | activity | entered through |
|---|---|---|
| 3, 17 | battle | `TransitionBattle` |
| 4, 18 | trade | `TransitionTradePoke` |
| 5, 19 | record mixing | `RecodeMatching$$Open` |
| 6, 20 | trainer card | `TransitionShowTrainerCard` |
| 7, 21 | ball capsules | `BallDecoMatching$$Open` |

8 to 16 do nothing. `RecodeMatching$$Open` and `BallDecoMatching$$Open` each open a message window
and send the console's own record at once — `NetDataRecodeData` (0x14, 694 bytes) and
`NetDataAttachSealNetData` (0x15, 143 bytes) — then wait for the partner's, and only on receiving
it (`StartRecodeTradeFlow`, `StartBallDecoTradeFlow`) apply the exchange and write the save. A
partner that never answers puts nothing in the console's save.

Measured for record mixing, with the console recruiting ("Échanger des données" in the Y menu,
state byte 5) and the client walking up: the console asks its player "voulez-vous faire un échange
de données ?", and on yes sends `NetDataTransitionData{5, 0}`, then 1.5 s later the 694-byte
`NetDataRecodeData` as a 205-byte zlib stream under the reliable header's flag 0x10. Its state byte
reads 19 (`NOW_RECORD`) while it waits; 44 s without an answer it shows "un des participants n'est
plus disponible" and returns to the room. The record carries the player's name, a group name, the
trainer id and 64-bit heap pointers in the unwritten fields, as the trainer record does.

`scratchpad/bdsp_native_layout.py --decode NetRecodeData FILE` prints one against the layout;
`room.parse` returns the head of it as `recode`. What one French Shining Pearl sent:

    RECORD.record[30]        thirty uint counters indexed by RECORD_ID: CLEAR_TIME 20240726,
                             DENDOU_CNT 1, CAPTURE_POKE 78, FISHING_SUCCESS 12, TAMAGO_HATCHING 3,
                             BEAT_DOWN_POKE 1034, ..., CONTEST_RATE_SINGLE 100
    RANDOM_SEED              group_name (16 chars), name (32 chars), int sex, int region_code (3),
                             ulong seed, ulong random, long time_stmp (a Windows FILETIME:
                             0x1d7dcd164934199 is 2021-11-18 23:09:52 UTC), int user_id (the
                             trainer id)
    TvRecodeData             five TV records (personality, ball decoration, fossil digging,
                             statue, fashion), each `bool isEmpty` (4 bytes), ints, and a
                             TV_STR_DATA name
    4 x TV_STR_DATA          {16-char value, byte language, genderId, two reserved}
    RECORD_HEAD              13-char username, int language, byte sex, int body_type,
                             uint uniqueID (the trainer id again)
    ten ints, six bytes      the per-TV branch values, then myVersion (0x31) and five
                             *IsNotEmpty flags

A battle ("Combattre", state byte 3 while recruiting) runs a longer ladder, and the recruiting
console waits on the joiner at every rung. Measured with the client as joiner:

| the joiner sends | the console does |
|---|---|
| `NetDataTalkData{GREETING}` | shows "Un combat ? OK ! Donne-moi juste une minute !" and waits |
| `NetDataSelectData{0}` (0x08) | shows "PkCamp est en train de choisir quoi faire..." and waits |
| `NetDataBattleTypeData{0}` (0x09, `BattleModeID.Single`) | asks its player "voulez-vous faire un combat selon ces règles ?"; on yes sends `NetDataTransitionData{17, 0}`, state byte 17, and opens the solo lobby at "connexion en cours" |
| `NetDataBattleMatchingJoin` (0x30) `{uint id, byte stationIndex, index, language, colorId, avatarId, sexId, cassetVersion}` | answers with its own join (`id` its trainer id, station 0, index 0) and relays the joiner's back; the joiner's character appears in the lobby's second slot |
| `NetDataBattleMatchingReady` (0x32, empty) | `BattleMatchingManager$$ReceiveReadyData`: when every member is ready, `NetDataBattleMatchingState{0, 6}` (0x33) — `MatchingState.SelectBattleTeam`, 4 and 5 skipped for a solo battle — and its player gets the team-selection button |
| nothing | on the player's team choice, six `NetDataBattleMatchingSelectPokemon` (0x38, 481 bytes), then "en attente d'autres personnes" |

The 0x38 body is the layout in the table above: a 328-byte encrypted PB8 whose checksum verifies
and whose species read back the team the player picked, in order,
twenty `SealParam` slots holding the same unwritten heap bytes in all six with `affixSealCount` 0,
`attachPokemonId` and `attachPersonalRnd` 0, `index` 0 to 5 and `num` 6. The joiner's `id` in 0x30
is not checked against anything: 0x0badc0de was accepted. `BattleMatchingManager.MatchingState` is
None 0, Initialize 1, Load 2, RecruitmentMember 3, SelectTeamMember 4, SelectRule 5,
SelectBattleTeam 6, SelectPokemon 7, GoBattle 8, Result 9, Resume 10, Closing 11,
LeavedOtherMembers 12.

`--inject-file PATH` on `bin/bdsp_connect.py` sends each new `ID:HEX` line of the file on the
reliable window while the association stands, which is how a ladder like this is climbed in one
association.

`RECORD_HEAD.sex` read 0 and `RANDOM_SEED.sex` 1 in the same record. The record is 1.3.0's
`RECORD`, `RANDOM_SEED` and `RECORD_HEAD` from the `DPData` namespace marshalled at pack 4, and the
`TvRecode*` structs at pack 8; no padding results at these field sizes.

Ball capsules run the same way ("Déco Capsule", state byte 7 while recruiting):
`NetDataTransitionData{7, 0}`, state 21 (`NOW_BALL_DECORATION`), then 1.8 s later the 143-byte
`NetDataAttachSealNetData` as a 116-byte zlib stream. Its first three bytes are the seal count, the
3D-edit flag and the template flag; then twenty `SealParam{short x, short y, short z, byte id}`.
A capsule with 19 stickers placed them all at a distance of 100 from the origin, slot 19 empty.
45 s without an answer the console shows "quelqu'un a mis fin à la communication" and returns to
the room.
