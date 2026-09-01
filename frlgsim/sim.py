"""The per-VBlank orchestrator - wires transport <-> crypto <-> Pia <-> FSM.

Two phases:
  S0 (connection): the ConnectionManager completes Net + Session(new) + RTT so the host
     registers us as a peer (this is what makes the "OK" prompt appear). Until then NO trade
     traffic is emitted.
  S1+ (trade): once connected, the TradeEngine's per-VBlank RFU slots ride Reliable(10).

Station VAR IDs are LEARNED from the wire (Pia header = [dst_var][src_var]; footer = dest var):
on each IN packet we record our id (= header dst) and the host's (= header src) and use them in
every OUT header/footer. Addressing: RTT -> broadcast, Net/Session/Reliable -> unicast to host.
A capture path mirrors every datagram to a .jsonl so it can be decrypted/analysed offline.
"""

import json
import os
import time

from . import crypto as cryptomod, reliable, gbaframe, rfu, pia_connect, ni, linkplayer

RELIABLE_SEQ_START = 0xFFF0

# The reliable layer runs on a millisecond clock; the sim ticks once per VBlank, so convert the VBlank
# counter to ms at the link boundary (timestamps for the RTO timer + RTT samples). 59.727 Hz VBlank.
MS_PER_VBLANK = 1000.0 / 59.727

# Max Reliable messages packed into ONE Pia datagram (observed: the reference capture batches up to 9/datagram). We
# coalesce a VBlank's retransmits + K acks + the T slot + the ctrl-ack into one datagram (chunked at
# this size) instead of one datagram per frame - the prime BufferIsFull lever.
RELIABLE_BATCH_MAX = 9

# LIVE-only cap on NEW standby (0x6600/0x5F00) frames emitted per count (live fix: standby flood
# deadlock). The reference capture sends each standby ~3-4x then stops; emitting every VBlank keeps the host
# in the same round forever (it sees continuous count=N) -> mutual deadlock + buffer flood. Bounding +
# reliable retransmit (live) matches the reference capture. Offline keeps the unbounded cadence its MockHost depends on.
BARRIER_EMITS = 6

# Pia reliable retransmit. The RTO lives entirely in ReliableLink: RTO = 33ms + 1.4*median(RTT), no clamp
# and no exponential backoff, driven by RTT samples taken from the RTT protocol (see _drive_reliable /
# the RTT feed in process_datagram). The retransmit is GAP-TARGETED (RTX_GAP_LIMIT) in the high-volume
# block/trade phase and whole-window for the tiny NI/seat phase (so the few critical NI frames get through).
RTX_GAP_LIMIT = 1          # block/trade phase: re-send only the gap (the peer buffers out-of-order)
RTX_GAP_LIMIT_NI = 2       # NI/seat phase: a slightly longer tail (a few critical frames), still bounded
# Pia reliable congestion control. The reliable layer (frlgsim/reliable.py) defaults to the console's
# settings: a large window, RTO = 33ms + 1.4*median(RTT), and fast-retransmit on a single NACK. The console
# earns those on a near-constant-latency local radio (median RTT ~= max RTT, and a NACK genuinely means
# loss). This LINK is different - userspace Wi-Fi with a ~50ms MEDIAN RTT but a ~1s TAIL (~20x jitter) and
# almost no real loss - so the console settings would collapse into a self-sustaining retransmit storm (a
# NACK fires for a frame merely in flight; the resend adds air contention; contention raises the jitter;
# the jitter creates more apparent gaps). So the driver overrides a few knobs, each a DOCUMENTED DIVERGENCE
# that defaults to the console behavior in reliable.py and only matters because this link breaks the
# console's assumptions:
#
#   MAX_INFLIGHT - the shared reliable send window. It must stay SMALL on this link: a larger window puts
#     more frames in flight than the host's receive side tolerates, and it faults with an in-game
#     Communication error (measured: both 18 and 128 fault shortly before the save; 6 is the ceiling and
#     completes the trade). Emission is FREE-RUN (one datagram per VBlank, below) rather than paced to the
#     host's poll arrivals, so in steady state in-flight self-limits well under the window - the window is
#     the safety cap, not the pacer. (K_INFLIGHT_MAX bounds the K layer independently so a K-ack
#     burst can never starve it.)
#   RTT_JITTER_K - the RTO must cover the JITTER, not just the median, or every slow-but-not-lost frame in
#     the 1s tail is retransmitted prematurely. rto() adds K * MAD(RTT) when this is > 0 (0 = console).
#   DUP_NACK_THRESHOLD - require this many agreeing NACKs before fast-retransmitting a hole. One NACK means
#     loss on the console; here it usually means the frame is still in flight (it lands ~50ms-1s later), so
#     resending on a single NACK resends in-flight frames. (The console's dup-NACK field is off / 1; we
#     turn it on for the bridge.)
#   RTO_CEIL_MS - clamp the RTO so a hole recovers in bounded time. The link is fast (~18ms round-trip),
#     so the RTO normally sits ~100ms; the clamp just bounds the worst case.
#   RTO_BACKOFF - DISABLED (1.0 = console). Backoff was tried (the theory being that retransmits were
#     futile resends of frames a slow host already had); it caused a MASSIVE regression - recovery latency
#     blew up to multiple seconds and the post-party-block transfer crawled/deadlocked. So the retransmits
#     are NEEDED, not futile: a stuck frame genuinely takes many sends to get through, and with a lean
#     window one stuck hole blocks the whole window - which means recovery must be FAST, never slowed. Keep
#     backoff off here.
#   RTO_BOOTSTRAP_MS - the RTO used ONLY while we have NO RTT samples yet (the connect phase); NOT a floor.
#     With no samples the console returns no RTO (no timer-driven retransmit) - fine on a clean radio, but on
#     the bridge it LOSES the connect-phase reliable frames: our 'J' (metadata/Initialized) + 'C' (RFU connect)
#     are sent the instant we go CONNECTED (~0.2s), BEFORE any round-trip, but the host's reliable side does
#     not come up until ~2s in (it engages in RESPONSE to our J/C, observed in frlg2/frlg3). A one-shot J/C is
#     simply lost -> the host never registers our connect -> 0 host proto-10 -> the pre-OK deadlock. A bootstrap
#     RTO (~200ms) makes J/C RETRANSMIT until the host engages. It is NOT a floor (the floor was measured to
#     ~2x the trade latency, p50 104->228ms): the instant the FIRST RTT sample arrives the pure formula
#     (33 + 1.4*median + jitter, capped by RTO_CEIL_MS) takes over with no minimum -> trade stays fast
#     (win2-slow-entry: p50 104ms / 5% NACK). So bootstrap fixes connect WITHOUT slowing the trade.
MAX_INFLIGHT = 24         # shared reliable window. Throughput here is window/RTO, and the RTO sits at its
                          # 670ms ceiling on this bridge, so 6 bought only ~9 reliable frames/s - far under
                          # the ~120/s (one 'T' + one 'K' per VBlank) the child owes a console polling at
                          # 60/s. Measured on hardware (j19): the window read 6/6 essentially the whole run
                          # while the console polled at 60/s and the child answered at 3-8/s, so the join
                          # handshake took ~9s and the console abandoned the room entry.
                          #
                          # 6 was chosen when 18 and 128 both comms-errored "shortly before the save". That
                          # evidence does NOT carry over: back then the K layer queued one frame per host
                          # poll and drained it oldest-first, so the generator could offer 4 frames/VBlank
                          # (~240/s) and a bigger window simply let more of that flood through - which is
                          # exactly "more frames in flight than the host's receive side tolerates". With K
                          # superseded to one per VBlank the offered rate is bounded by the VBlank CLOCK, not
                          # by the window, so the window can only ever release frames the child genuinely
                          # owes. Swept offline against the captured host stream: 6 -> 15/s, 12 -> 33/s,
                          # 24 -> 56/s, 48 -> 57/s at 120ms one-way / 10% loss. 24 is the knee - it reaches
                          # the console's native poll rate, and past it the clock binds instead.
RTT_JITTER_K = 4.0
DUP_NACK_THRESHOLD = 3
RTO_CEIL_MS = 670
RTO_BACKOFF = 1.0
RECV_NI_REACK_EVERY = 20  # re-ack the host's NI sub-frame every N repeats (it polls ~60/s)
# DO NOT RAISE THESE - it has been tried and it is strictly worse. The whole child registration
# must finish inside the parent's rfu_LMAN_establishConnection window of 240/360 frames = 4-6s
# [link_rfu_2.c:340-345, 522-527], and on hardware (j21, healthy at 60 host polls/s) the host needed
# TEN re-sends of one NI sub-frame over 2s before registering it, so one lost sub-frame eats half
# the budget. The obvious response - re-send sooner and more often - was tried at 4/4 (~15/s): j22
# died 0.7s after the host accepted us, against 6.6s at these values. The send window was not the
# limit in either run (5 of 24 outstanding), so this is NOT congestion; the host's librfu NI
# receiver is itself intolerant of the extra sub-frames. That reproduces the hazard already in
# NOTES.local.md, where an every-poll re-send dropped the link in 0.9s - and it was reproduced here
# even with the recv-NI ack given strict priority, so priority was not the explanation either.
# A lost NI sub-frame does not get fixed by sending more of them.
HOST_ACK_REPEAT_BEFORE_RESEND = 10   # repeats of one host ack before we assume a loss
NULL_REEMIT_EVERY = 12    # re-send the terminator every N polls (~5/s), not every VBlank
NI_ACK_WAIT_RESEND = 12   # while awaiting the host's ack of our current NI sub-frame, re-send it
                          # this often (~5/s) - the same proven pacing, but aimed at the sub-frame
                          # the host is actually waiting for instead of at a repeat-count guess.
NULL_REEMIT_MAX = 30      # ~6s of paced re-sends before giving up on a stuck host
RTO_BOOTSTRAP_MS = 200    # RTO while sampleless so the connect J/C retransmit until the host engages (NOT a floor)
# K-ack pacing: the K-ack is the emulator's ack of a received host poll. The host polls ~60x/s, so
# acking every poll offers ~60 reliable frames/s ON TOP of the per-VBlank 'T' - far more than this
# bridge carries (throughput is window/RTO: MAX_INFLIGHT 6 over an RTO that climbs to its 670ms
# ceiling is ~9 frames/s). Measured on hardware (joiner_entry_reference): the window filled with
# obsolete K and the child emitted 0-3 slots/s against a console polling at 60-97/s.
# So K SUPERSEDES rather than queues: only the NEWEST un-acked host ts is pending (K is a monotonic
# ts ack and the host re-sends any 'T' we leave un-acked, so an older K carries nothing a newer one
# does not), and at most ONE goes out per VBlank.
# The count it carries is NOT droppable, though. `k_seq` is the running total of host 'T' frames we
# have received, incremented on receipt, and the console's parent uses it as the DRAC ack that gates
# RfuMain2_Parent's `(lman.parentAck_flag & parentSlots) == parentSlots` [link_rfu_2.c:867]. That gate
# does nothing until the parent finalizes (RfuMain1_Parent takes the pre-FINALIZED branch), so an
# under-reported k_seq is invisible right up to the trade-room entry and then wedges it: gSendCmd is
# never cleared by MoveSendCmdToRecv, SEND_PLAYER_IDS never reaches the wire, and the parent stops
# transmitting altogether. Measured (j23): 247 host 'T', k_seq 51, one UNI frame then silence for 125s.
# K in-flight cap. This is now the ONLY bound on the K layer: a pending K goes out regardless of the
# send window, exactly like the child-liveness override below and for the same reason - a full window
# costs throughput, a withheld ack costs the link. Supersession makes that safe: at most ONE K is ever
# pending, so we offer at most one per VBlank and never more than K_INFLIGHT_MAX unacked at a time.
#
# Measured (j24, hardware): with K gated a slot TIGHTER than the 'T' the entry phase ran at out=24/24
# with k=0/s - our own idle UNI slots filled a window draining at ~2/s and locked the K out
# permanently, so the console never learned we had received its finalize poll and went quiet. The
# ordering was backwards: the K is not the droppable frame here, it is the frame the peer is blocked
# on. (The older worry - that K crowds out the recv-NI ack during a host NI flood - was written when K
# queued one frame per host poll. It cannot recur now that K supersedes to one pending frame.)
K_INFLIGHT_MAX = 4
# CHILD LIVENESS. Measured in joiner_entry_reference: the console polled at 60-97 'T'/s while the
# child emitted 0-3/s, going quiet for 0.6s, 0.8s, 1.0s, 1.2s, 2.2s, 2.7s and 2.9s at a stretch -
# because the Pia send window was full (see the K flood above) or _gba_frame() had nothing new to
# say. The host's own NI took 11.6s to complete instead of ~0.2s, SEND_PLAYER_IDS did not arrive
# until 22s after the host's 'A', and the LinkPlayer block exchange then died mid-stream.
#
# For scale, FRLG configures librfu with MC_TimerCount = 32 [link_rfu_2.c:129], documented as
# "x16.7ms" [AgbRfu_LinkManager.h:122] = ~534ms, with linkRecovery_enable = FALSE
# [link_rfu_2.c:136] - no recovery, straight to RFU_DISCONNECT_ERROR. Treat that as an ORDER OF
# MAGNITUDE, not a proven bound on 'T' silence specifically: the reference capture has a real
# console sending zero 'T' across the ~2.4s join-textbox gap, so the emulator's RFU wrapper clearly
# keeps something alive below the game slot. What IS established is the shape - this codebase's most
# frequent bug by far is our side going quiet while the console waits on us - so the per-VBlank
# child slot is treated as a liveness obligation and not merely as data: the congestion window may
# DELAY it, but it must not silence it indefinitely.
CHILD_SILENCE_LIMIT = 20   # VBlanks (~335ms) without a child 'T' before we emit one regardless

# Ceiling on the liveness override, as a multiple of the send window. The override exists to outlast
# a congested link, NOT to keep talking to a peer that has gone away: once the console stops
# responding entirely, every forced slot goes unacked forever and `outstanding` grows without bound
# (observed live at 74/24 and climbing, with rx frozen). Past this the peer is genuinely gone and
# more slots cannot help, so the window resumes being a hard cap and the run's leave tail ends it.
SILENCE_OVERRIDE_CEIL = 2  # allow outstanding up to SILENCE_OVERRIDE_CEIL * max_inflight
# Poll credits. librfu's child readies a slot only when the parent's poll actually landed
# [MscCallback_Child: rfu_UNI_readySendData under recv.newDataFlag], so one child slot per host 'T'
# is the native cadence. Measured (j29, hardware): free-running at 60/s against a host polling at
# 3/s pinned out=24/24 and the RTO at its 670ms ceiling, and the console's parent is stop-and-wait
# on our K-ack - so every surplus idle slot directly delayed the one frame it was blocked on, and
# its LinkPlayer block crawled at ~1 fragment/s until it gave up. Credits cap the burst; the
# CHILD_SILENCE_LIMIT floor still guarantees we never go quiet on a host that has paused.
SLOT_CREDIT_MAX = 2        # host polls we may owe a reply to at once
# Slots we may spend per received poll WHILE WALKING TO THE SEAT. The console's runway in the trade
# room is finite and small - measured (j50): it polls at 13-16/s for about six seconds after entering
# the room and then goes quiet, which is ~85 slots. The route is 112 frames and the peer advances our
# avatar ONE frame per slot it receives, so at one slot per poll we run out of runway mid-walk; j50
# did finish the route and sit, but only at 69.7s, 31s after starting, long after the console had
# given up. Two per poll fits 112 frames into that window with margin.
# NOT free-running: j43 emitted held-keys at 57/s uncorrelated with the console's polls (~4x its
# rate, in one unbroken run) and it stopped transmitting after five slots. This stays proportional to
# the console's own cadence, just doubled, and only for the ~112 frames of the walk.
WALK_SLOTS_PER_POLL = 2
ACK_PERIOD = 2             # delayed-ack interval: a standalone bulk-ack is owed at most every ~33ms (2
                           # VBlanks). The ack piggybacks on a data datagram whenever one is being sent this
                           # VBlank and goes out standalone only when one is owed (received data / a gap to
                           # NACK) and the floor has elapsed. A faster ack frees the peer's send window
                           # sooner; the correct RTT-driven RTO keeps this from flooding the half-duplex link.
COMPRESS_MIN = 62          # zstd-compress an OUT datagram iff its message body is >= this many bytes - the
                           # EXACT rule the real Switch host uses (measured across the reference captures IN: largest raw=61,
                           # smallest compressed=62, zero overlap = a clean size threshold). Below it, frames
                           # go raw. Combined with crypto.ZSTD_LEVEL=4 this makes our wire BYTE-IDENTICAL to a
                           # real FRLG joiner. Small frames (single gba slot / ack ~16-37B) stay raw as on HW.

# The child 'T' timestamp (body[0:4], u32 LE) is a per-NEW-frame counter that must INCREASE per new
# frame and be REUSED on a Pia retransmit. The reference capture's child seeded it ~0x362e; the host
# appears to gate on monotonicity + rate, not an absolute base (uncertain on the live link), so we seed nonzero.
TS_SEED = 0x0000362E


class Sim:
    def __init__(self, transport, pia_crypto, engine, our_ip, host_ip, *, conn=None,
                 our_var=0xc493, compress=False, header_flags=0x50, capture_path=None,
                 linkstate=None, connect_id=None, log=lambda *a: None):
        self.t = transport
        self.crypto = pia_crypto
        self.engine = engine
        # Held-keys overworld link-state engine [frlgsim/linkstate.py]. When present, the sim emits a
        # 0xBE00 SEND_HELD_KEYS keepalive on an idle VBlank ONLY while engine.in_seat_phase (the
        # overworld/cable-seat phase, entry P0..P3) - mirroring SendKeysToRfu, which the real child
        # runs ONLY while gRfu.callback == SendKeysToRfu [link_rfu_2.c:1069-1080,1089]. That callback
        # is cleared the instant we warp out of the cable seat (Task_StartWirelessTrade case 0
        # ClearLinkRfuCallback() -> gRfu.callback = NULL [cable_club.c:918]), BEFORE the trade menu's
        # party exchange (BufferTradeParties [trade.c:935]) and the later gMain.callback1 =
        # CB1_UpdateLink swap [trade.c:1085]. So from the party exchange (S4) through the trade FSM and
        # the post-trade save an idle VBlank is a bare all-zero idle slot, NOT 0xBE00; held keys are
        # only re-armed back in the overworld field [field_fadetransition.c:226]. Held keys NEVER
        # override a real SEND_BLOCK/LINKCMD slot (we ask the engine first; held keys take an IDLE slot
        # only) - and engine.in_seat_phase latches off at the party exchange (entry.seat_phase_over).
        self.linkstate = linkstate
        self.conn = conn                # ConnectionManager (None = trade-only, e.g. replay)
        # LIVE (conn present): bound the engine's barrier standby burst per count so a never-completing
        # round can't flood the host (offline keeps the every-VBlank cadence its MockHost timing needs).
        if conn is not None and hasattr(engine, "barrier"):
            engine.barrier.max_emits = BARRIER_EMITS
        # LIVE: gate READY_TO_TRADE on the FULL BufferTradeParties (ribbons/settle) so we don't send it
        # mid-exchange (the offline MockHost model has no mail/ribbons, so this stays off there).
        if conn is not None and hasattr(engine, "_live"):
            engine._live = True
        self.our_ip = our_ip
        self.host_ip = host_ip
        self.broadcast = host_ip.rsplit(".", 1)[0] + ".255"
        self.compress = compress
        self.header_flags = header_flags
        self.log = log
        self.info = getattr(log, "info", log)   # clean milestone sink (default-mode narration)

        self.slot = rfu.SlotBuilder()
        # child 'T' frame counter (u32). One per NEW 'T' we emit; reused on a Pia retransmit (the
        # retransmit re-offers the already-built frame bytes, so ts is baked in at build time).
        self.ts = TS_SEED
        # emulator 'K' ack layer: the host sends a 'T' per VBlank and we ack it with a 'K' (the host
        # sends us NO K). `k_seq` is a CUMULATIVE COUNT OF HOST 'T' FRAMES RECEIVED, not a counter of
        # the K frames we send - it is incremented on RECEIPT of each unique host ts, and whichever K
        # actually goes out carries the running total. Verified in joiner_entry_reference: only 96 K
        # frames reached the console yet their k_seq ran 1..532 with large jumps (16->61, 138->259,
        # 300->434), exactly tracking the host 'T' index, and the console accepted every one. So gaps
        # in the K stream are fine; a k_seq that under-reports what we have received is not.
        # `mid` (1-based position within the OUT Pia datagram) is assigned at flush.
        self._k_seq = 0                  # host 'T' frames received so far = the value the next K carries
        self._acked_ts = set()           # host T ts values already K-acked (dedup)
        self._pending_k_ts = None        # NEWEST host ts still owing a K (older ones are superseded)
        self._k_seqs = set()             # reliable seqs of OUR K-acks still in flight (for K_INFLIGHT_MAX)
        # Emission counters for the live diagnostic: the joiner's whole failure mode is "we stopped
        # talking", and it is invisible without a rate. host_t_in / t_out are host polls received and
        # child slots emitted; k_out is K-acks emitted. [live] logging is verbose-gated and --verbose
        # is banned on live runs, so these are reported on the INFO sink by frlgtrade.py.
        self.host_t_in = 0               # host 'T' polls received (NI sub-frames, UNI and idle)
        self._last_t_tick = 0            # VBlank of the last child 'T' queued (CHILD_SILENCE_LIMIT)
        self.silence_forced = 0          # child slots emitted purely to satisfy the liveness bound
        self.max_silence = 0             # worst run of VBlanks with no child 'T' (the run classifier)
        self.t_out = 0                   # child 'T' frames queued (NEW frames, not retransmits)
        self.k_out = 0                   # child 'K' acks queued
        # NI sender machine: after the host accepts our 'C' (the 'A' frame), the child
        # runs the librfu NI sender to deliver its RfuGameData before any UNI trade traffic. Built
        # lazily once we know our identity (from the engine's LinkPlayer); None until the NI phase.
        self._ni = None
        self._ni_done = False
        self._ni_built = False
        # librfu's NI transfer is STOP-AND-WAIT: the receiver takes one sub-frame, acks it, and only
        # then accepts the next. This repo's own parent implements exactly that
        # [rfu_leader.py _parent_waiting], but NISender did not - next_slot() advanced on every call,
        # so the child dumped all six sub-frames in ~92ms. The host registered the first, acked it,
        # and the rest arrived while its NI receiver was still on that one. Recovery then fell to the
        # "host repeated its ack 10 times" guess at ~5/s, which measured ~2s PER sub-frame on
        # hardware (j21) - roughly 10s for the transfer against the parent's 4-6s
        # establishConnection budget, so the host disconnected every time. Sending faster made it
        # worse (j22, dead in 0.7s) because that just puts more out-of-sequence sub-frames into the
        # host's NI receiver. Gate on the ack instead: one sub-frame in flight, advance the moment
        # the host acknowledges it, so a clean link finishes the transfer in ~6 round-trips.
        self._ni_awaiting = None     # (state, n, phase) of the sub-frame awaiting the host's ack
        self._ni_wait_ticks = 0      # polls spent awaiting it (paces the re-send)
        # RECV-side NI: right after the host acks OUR send-NI it runs its OWN librfu NI
        # sender (its connection/join-status data). The child must ACK every host NI sub-frame (ack=1,
        # mirroring state/n/phase) or the host's NI transfer never completes and the host faults the
        # link ("Communication error"). We DISCARD the host's NI data content (no reassembly needed).
        self._ni_recv = ni.NIReceiver()
        # recv-NI ack dedup: we hold the ack for the host's CURRENT NI sub-frame and re-emit it once per
        # DISTINCT sub-frame (it updates when the host advances) - NOT a growing queue. An append-per-host-
        # frame queue spammed hundreds of duplicate acks when the host re-sent a sub-frame under loss
        # (observed: out NI_END x125); a single current-ack stays 1:1 with the host's sub-frames.
        self._cur_ni_ack = None          # slot bytes for the latest host NI sub-frame's recv-ACK
        # ONE recv-NI ack in flight per host sub-frame. The recv-NI ack is idempotent (the host needs only
        # its CURRENT sub-frame acked) - so we queue at most one reliable ack for it and let the reliable
        # layer retransmit that one under loss, instead of queuing a fresh ack every poll. Queuing one per
        # poll piles a backlog of stale acks; in-order delivery then delays the host's needed ack until the
        # backlog drains, so the host advances ever-slower and the NI handshake deadlocks (a latent race).
        self._ni_ack_seq = None          # reliable seq of the recv-NI ack currently in flight (or None)
        self._ni_ack_bytes = None        # the _cur_ni_ack bytes that seq carries (to detect a sub-frame change)
        self._emitted_ni_ack = None      # set by _gba_frame when it returns a recv-NI ack, so _drive_reliable records its seq
        self._host_uni_seen = False      # host sent its first UNI slot (state 4) => its NI is done -> UNI
        # recv-NI must go QUIET at the host's NI NULL (observed Communication-error). The host re-sends
        # NI_END until it sees our ack, THEN sends NULL; after NULL there is a ~2.4s join-textbox gap
        # before UNI where the reference capture sends ZERO 'T'. We were re-emitting the stale NI_END ack right through
        # that gap -> a malformed/out-of-protocol slot -> in-game "Communication error". Stop acking at
        # NULL: emit _cur_ni_ack only until NULL is seen, then K/bulk-acks only until _host_uni_seen.
        self._host_ni_null_seen = False
        self._host_ni_ack_state = None    # LLSF state of the host's most recent ack of OUR send-NI
        self._host_ni_repeat = 0          # consecutive repeats of the host's current NI sub-frame
        self._host_ni_ack_key = None      # (state,n,phase) of the host's last ack of OUR NI
        self._host_ni_ack_repeat = 0      # how many times it has repeated that ack
        self._host_ni_resend = None       # the sub-frame it is waiting for, to re-send
        self._null_reemits = 0            # bounded re-sends of our NI terminator
        self._null_ticks = 0              # polls spent waiting to re-send it
        self._ni_status_logged = False    # logged the host's recv-NI join status once
        self.ni_rejected = False          # host returned a non-JOIN_GROUP_OK status -> abort the trade
        self.host_disconnected = False    # host sent a emulator 'D' (0x44) disconnect -> link closing
        self.out_seq = RELIABLE_SEQ_START
        # Pia packet id: PER-CHANNEL counters keyed by Pia-header dst var-id (observed: the reference capture keeps THREE
        # independent pktid counters - dst=0x0000 establishing, dst=0x0001 session/RTT (1..960), dst=
        # host-var reliable/data (1..4415)). A single global counter SKIPPED reliable pktids once RTT/
        # Session interleaved, risking host-side drop/reorder of our reliable frames -> under-ack ->
        # BufferIsFull. Each channel starts at 1 and skips 0 on rollover; establishing frames force 0.
        self._pktid_by_dst = {}
        self.last_in_seq = 0
        self._recv_hi = None              # highest host reliable seq seen (wrap-aware) for the cumulative ack
        # Pia RELIABLE sliding-window connection. The peer ignores reliable DATA until we OPEN the stream
        # with an Initialized frame (the metadata/title frame); the two sides then bulk-ACK each other.
        # ReliableLink does the RETRANSMISSION (frames drop on this radio) + in-order delivery, with an
        # RTT-driven RTO and selective-repeat recovery. GAP-TARGETED retransmit (RTX_GAP_LIMIT, in
        # _drive_reliable) re-sends only the gap - the peer buffers out-of-order, so the gap alone drains
        # its run. Live only (conn!=None); offline replay/tests keep the bare path.
        self.rel = reliable.ReliableLink(start=RELIABLE_SEQ_START, max_inflight=MAX_INFLIGHT,
                                         rtt_jitter_k=RTT_JITTER_K, dup_nack_threshold=DUP_NACK_THRESHOLD,
                                         rto_ceil_ms=RTO_CEIL_MS, rto_backoff=RTO_BACKOFF,
                                         rto_bootstrap_ms=RTO_BOOTSTRAP_MS)
        self._rel_opened = False
        self._ack_owed = False           # received host reliable DATA we haven't bulk-acked yet
        self._last_ack_tick = -100       # last tick we emitted a ctrl bulk-ack (steady-cadence floor)
        self._tick = 0                   # VBlank counter, drives the retransmit timers
        # emulator RFU connect ('C') frame: our OWN 2-byte RFU connection id, self-chosen. Any nonzero
        # value works - the host does not match it, it just seats our slot - so a random nonzero id is
        # passed in. None (offline replay/tests) => we do NOT send a 'C' (the host stays bulk-ack-only
        # until it sees one).
        self._connect_id = bytes(connect_id) if connect_id else None
        self._gba_conn_sent = False
        self._gba_accepted = False        # have we seen the host's emulator connect accept ('A')
        # Emission is POLL-PACED with a liveness floor: _drive_reliable spends one credit (one host
        # 'T' received) per child slot, and emits regardless once CHILD_SILENCE_LIMIT VBlanks have
        # passed with nothing sent. That is librfu's own child cadence, and it still keeps us fed
        # across the NI->UNI seam - the earlier free-run version was written to fix silence there, but
        # the floor is what actually fixes it; free-running only added congestion (see SLOT_CREDIT_MAX).
        self._slot_credit = 0
        self._last_seat_emit = -100      # last tick we emitted a seat/leave held-keys (keepalive floor)
        self._seen_in = set()
        self.rx_count = self.tx_count = 0
        self.rx_fail = 0                 # host datagrams that failed to decrypt (SSID/key mismatch)
        self.rx_protos = {}              # proto id -> count of IN Pia messages seen
        self._dbg = None                 # set to a list to capture per-VBlank block-send emission decisions

        # our var id is SELF-CHOSEN and announced; the host's is LEARNED from incoming headers
        # (the host's first packet has dst=0 until it knows ours, so only src is reliable).
        self.our_var = our_var.to_bytes(2, "big")
        self.host_var = reliable.STATION_HOST.to_bytes(2, "big")
        self._learned = False
        # keep the ConnectionManager's self-chosen var id in sync with ours (it stores an int)
        if conn is not None:
            conn.our_var = int.from_bytes(self.our_var, "big")

        self._cap = open(capture_path, "w", buffering=1) if capture_path else None
        if self._cap:
            self._cap.write(json.dumps({"rec": "meta", "event": "session", "kind": "sim",
                                        "ip": our_ip, "host": host_ip,
                                        "ssid_hex": pia_crypto.ssid.hex(),
                                        "broadcast": self.broadcast}) + "\n")
        self._t0 = None

    @property
    def connected(self):
        return self.conn is None or self.conn.connected

    @property
    def _now_ms(self):
        """The VBlank counter as milliseconds - the clock the reliable layer runs on."""
        return self._tick * MS_PER_VBLANK

    # ---- capture -----------------------------------------------------------
    def _capture(self, direction, datagram, src, dst):
        if not self._cap:
            return
        if self._t0 is None:
            self._t0 = time.monotonic()
        self._cap.write(json.dumps({
            "rec": "pkt", "seq": self.rx_count + self.tx_count, "t": time.monotonic() - self._t0,
            "dir": direction, "proto": 17, "src": src, "dst": dst,
            "len": len(datagram), "hex": datagram.hex(),
        }) + "\n")

    # ---- RX ----------------------------------------------------------------
    def process_datagram(self, datagram, src_ip):
        if not cryptomod.is_pia(datagram):
            return False
        self._capture("in", datagram, f"{src_ip}:12345", f"{self.our_ip}:12345")
        hdr = cryptomod.PiaHeader.unpack(datagram)
        # Pia header is [dst_var][src_var]; the host announces its own var id as src.
        if not self._learned and hdr.src != 0:
            self.host_var = hdr.src.to_bytes(2, "big")
            self._learned = True
            if self.conn:
                self.conn.learn_ids(self.our_var, self.host_var)
        pt = self.crypto.decrypt(datagram, src_ip)
        if pt is None:
            self.rx_fail += 1
            if self.rx_fail <= 5:
                self.log(f"[sim] RX decrypt FAILED from {src_ip} hdr.src=0x{hdr.src:04x} "
                         f"(SSID/key mismatch?) - host msg never reaches the handshake")
            return False
        app, _ = cryptomod.decompress(pt)
        msgs, _, _ = reliable.parse_app(app)
        for m in msgs:
            self.rx_protos[m.proto] = self.rx_protos.get(m.proto, 0) + 1
        if self.rx_count < 8:
            self.log(f"[sim] RX ok from {src_ip}: protos={[m.proto for m in msgs]} "
                     f"(1=Net 3=RTT 10=Reliable 13=Session)")
        for m in msgs:
            if m.proto == reliable.PROTO_RELIABLE:
                rl = reliable.parse_reliable(m.payload)
                if rl is None:
                    continue
                if self.conn is None:                 # offline replay: feed frames as they arrive
                    self._note_in_seq(rl.seq)
                    if rl.flagsA & 0x01 and rl.payload[:1] == b"\x57":
                        self._on_gba_in(rl.payload)
                elif rl.flagsA & 0x01:                # live AppData: PROCESS AS IT ARRIVES (the emulator
                    # is order-tolerant - it reassembles blocks by fragment index and re-pulls), so we
                    # deliver each UNIQUE frame the instant it lands (never stall the synchronous RFU
                    # exchange on a gap). The PIA ACK is an honest selective-repeat ack: note_received tracks
                    # the contiguous recv_next + the out-of-order set, and ack_payload carries a selective
                    # MASK so the peer fast-retransmits exactly its drops.
                    self._ack_owed = True
                    if rl.seq not in self._seen_in:
                        self._note_in_seq(rl.seq)
                        if rl.payload[:1] == b"\x57":
                            self._on_gba_in(rl.payload)
                    self.rel.note_received(rl.seq)       # contiguous recv_next + recv_ooo for the selective ack
                else:                                 # live FLAGSA_CTRL: peer's bulk-ack of OUR sends
                    ackid, mask = reliable.parse_bulk_ack(rl.payload)
                    # frees acked frames (cumulative + selective mask); now_ms lets it sample the
                    # reliable round-trip (un-retransmitted frames) to drive the RTO.
                    self.rel.on_ack(ackid, mask, now_ms=self._now_ms)
            elif self.conn:
                self.conn.on_message(m.proto, m.payload, tick=self._tick)
        self.rx_count += 1
        return True

    def _on_gba_in(self, payload):
        """Dispatch one IN emulator frame (host/parent) by type.
          'A' (0x41): the host's emulator connect ACCEPT - the RFU link is up; arm the NI phase.
          'T' (0x54): a host slot frame. EVERY unique host T ts is K-acked (incl. idle slot_len<=1).
              UNI 'T' (the mpId rows) is fed to the trade engine; a host NI 'T' is the host's game-data
              handshake which our recv side must (eventually) ack - it is consumed here (its slots are
              not UNI, so the engine ignores them) and acked via the same per-ts K.
          'K' (0x4b): the host never sends us K, so this is informational only."""
        rec = gbaframe.parse_in(payload)
        if rec is None:
            return
        typ = rec.get("type")
        if typ == "A" and not self._gba_accepted:
            self._gba_accepted = True              # host's emulator connect ACCEPT (0x41)
            self.log(f"[sim] host ACCEPTED emulator connect ('A' 0x41): {payload[:10].hex()} "
                     f"-> our slot is seated; RFU link up, starting the NI handshake")
            self.info("Host accepted the link.")
            return
        if typ == gbaframe.TYPE_D and not self.host_disconnected:
            # host emulator DISCONNECT ('D' 0x44): the RFU link is going down. Surface it (a clean leave
            # signal) instead of silently ignoring it and spinning on a dead link.
            self.host_disconnected = True
            self.log("[sim] host emulator DISCONNECT ('D' 0x44) - RFU link closing")
            return
        if typ != "T":
            return
        # K-ack EVERY unique host T ts (one K per unique ts; host idle T is still acked).
        ts = rec.get("ts")
        self.host_t_in += 1
        if ts is not None and ts not in self._acked_ts:
            self._acked_ts.add(ts)
            self._k_seq += 1                       # cumulative host-'T' receive count (see __init__)
            self._pending_k_ts = ts                # supersede any older pending K (see K_INFLIGHT_MAX)
            if len(self._acked_ts) > 8192:         # bound memory on a long session
                self._acked_ts = set(list(self._acked_ts)[-2048:])
        # RECV-side NI: a host NI-window 'T' (NI_START/NI/NI_END/NULL, NOT UNI) carries record['ni'].
        # When it is the host's OWN outgoing NI (ack=0) enqueue a recv-NI ACK slot MIRRORING its
        # (state, n, phase) with ack=1, sz=0 (the host's NI data content is discarded). NIReceiver
        # marks the host's NI complete on the host NI_END (or NULL). This is ORTHOGONAL to the K layer
        # above (the host NI 'T' is still K-acked); the ack rides a SEPARATE child 'T' (see _gba_frame).
        ni_rec = rec.get("ni")
        if ni_rec is not None:
            ack_slot = self._ni_recv.on_host_ni(ni_rec)
            if ack_slot is not None:
                if ack_slot == self._cur_ni_ack:
                    # The host is REPEATING the same sub-frame, which means it has not seen our
                    # ack. Emitting the ack once per distinct sub-frame assumes reliable delivery;
                    # observed on hardware: the host re-sent NI_START 480 times over 8s, timed out
                    # its own NI, and the entry handshake never recovered. Periodically clear the
                    # in-flight marker so the ack is re-emitted - every poll would spam hundreds of
                    # duplicates (a documented past failure), so re-ack on a slow cadence.
                    self._host_ni_repeat += 1
                    if self._host_ni_repeat % RECV_NI_REACK_EVERY == 0:
                        self._ni_ack_bytes = None
                        if self._host_ni_repeat == RECV_NI_REACK_EVERY:
                            self.info("Host is repeating its NI sub-frame; re-acking it.")
                else:
                    self._host_ni_repeat = 0
                self._cur_ni_ack = ack_slot         # latest host NI sub-frame -> the ack to re-emit
            if ni_rec.get("ack") == 1:
                # The host's ack of OUR send-NI names the last sub-frame it registered, so the one
                # it is waiting for is the next one we emitted. A REPEATED ack means that next
                # sub-frame was lost.
                key = (ni_rec.get("state"), ni_rec.get("n"), ni_rec.get("phase"))
                self._host_ni_ack_state = ni_rec.get("state")
                if key == self._host_ni_ack_key:
                    self._host_ni_ack_repeat += 1
                    if (self._host_ni_ack_repeat >= HOST_ACK_REPEAT_BEFORE_RESEND
                            and self._ni is not None and self._host_ni_resend is None):
                        self._host_ni_resend = self._ni.resend_after(*key)
                else:
                    self._host_ni_ack_key = key
                    self._host_ni_ack_repeat = 0
                    self._host_ni_resend = None
                    self._null_reemits = 0
                    self._null_ticks = 0
            if ni_rec.get("state") == rfu.LCOM_NULL and ni_rec.get("ack") == 0:
                self._host_ni_null_seen = True       # host's NI terminator -> stop acking, go quiet
            # host join STATUS: log it once; a non-OK value means the host REJECTED us (full
            # lobby / blacklist / version mismatch), so flag it - else we'd ack forever then hang on a
            # UNI that never comes.
            st = self._ni_recv.status
            if st is not None and not self._ni_status_logged:
                self._ni_status_logged = True
                if st == ni.RFU_STATUS_JOIN_GROUP_OK:
                    self.log(f"[sim] host NI join status = JOIN_GROUP_OK ({st})")
                else:
                    self.ni_rejected = True
                    self.log(f"[sim] WARNING: host NI join status = {st} (NOT JOIN_GROUP_OK=5) -> host "
                             f"REJECTED our join; the trade cannot proceed")
        # The host's FIRST UNI slot (parent LLSF state 4) means its NI is finished and it has entered the
        # UNI trade phase -> our recv-NI is done. This is the transition trigger (it guarantees we never
        # send a UNI slot before the host itself is in UNI, which would fault its RFU link manager).
        if rec.get("llsf_state") == 4:
            self._host_uni_seen = True
        # Count every host 'T' (NI sub-frame, NI ack, UNI, or idle keepalive) as one delivered host slot.
        # _slot_credit is host slots delivered but not yet answered - the emission pacer spends it.
        # The seat walk earns WALK_SLOTS_PER_POLL per poll (see the constant): its runway is short.
        _walk = self.linkstate is not None and self.linkstate.walking
        _per_poll = WALK_SLOTS_PER_POLL if _walk else 1
        self._slot_credit = min(self._slot_credit + _per_poll,
                                SLOT_CREDIT_MAX * _per_poll)
        # Feed the host's UNI slots (the mpId gRecvCmds) to the trade engine; the parse_in record's
        # `positional` alias is exactly what the engine reads. A host idle/NI 'T' has no
        # UNI slots, so feed_in_frame is a no-op for it (it still got K-acked + counted as a tick).
        self.engine.feed_in_frame(rec)

    def _note_in_seq(self, seq):
        if seq in self._seen_in:
            return
        self._seen_in.add(seq)
        if len(self._seen_in) > 4096:
            self._seen_in = set(list(self._seen_in)[-1024:])
        if ((seq - self.last_in_seq) & 0xFFFF) < 0x8000:
            self.last_in_seq = seq

    # ---- TX ----------------------------------------------------------------
    def _next_pktid(self, dv):
        """Per-CHANNEL Pia packet id keyed by header dst var-id (observed: the reference capture keeps independent
        counters per dst - dst=0x0001 session/RTT (1..960), dst=host-var reliable/data (1..4415)).
        Each channel counts from 1, skipping 0 on rollover, so the reliable channel stays contiguous
        even when RTT/Session frames interleave on their own dst. The establishing connection-exchange
        frames (Net 0x12 / Session join) ride pktid 0 by passing pktid=0 explicitly to _send."""
        pktid = self._pktid_by_dst.get(dv, 1)
        self._pktid_by_dst[dv] = pktid + 1 if pktid < 0xFFFF else 1
        return pktid

    def _send_messages(self, messages, *, dst_var=None, src_var=None, compress=False,
                       footer=True, establishing=False, unicast=True, pktid=None, footer_var=None):
        """Frame N Pia messages into ONE datagram and send it (observed: the reference capture BATCHES up to 9 reliable
        messages per datagram; we used to emit one datagram per frame -> ~1.6x+ datagram flood ->
        host SEND-buffer overflow (BufferIsFull)]. `messages` = [(proto, payload), ...] sharing one
        header (same dst/src/pktid channel). The encrypted plaintext is:

            [ message* , optionally zstd-compressed AS A WHOLE ]
            [ footer: 2-byte recipient (destination) variable id, UNCOMPRESSED, only if footer ]
            [ 0xFF padding so the total is a multiple of 16 ]

        header byte5 = (padding_size << 4) | flags, flags = (1 if zstd) | (2 if establishing); the
        footer-size byte = len(footer). One pktid per datagram (per-channel), NOT per message."""
        if not messages:
            return None
        dv = dst_var if dst_var is not None else int.from_bytes(self.host_var, "big")
        sv = src_var if src_var is not None else int.from_bytes(self.our_var, "big")
        body = b"".join(reliable.build_message(m[0], m[1], m[2] if len(m) > 2 else None)
                        for m in messages)
        # zstd-compress like a real FRLG joiner: the host compresses iff the message body is >= 62 bytes
        # (COMPRESS_MIN), a pure size threshold. `compress=True` (the Session join) forces it regardless. At
        # crypto.ZSTD_LEVEL=4 + the window-frame header this is byte-identical to the console. Auto-compress
        # only when zstd is actually available (an explicit compress=True still raises if it isn't, as before).
        do_zstd = compress or (len(body) >= COMPRESS_MIN and cryptomod.HAVE_ZSTD)
        if do_zstd:
            body = cryptomod.compress(body)
        fsize = 0
        if footer:
            # footer = the RECIPIENT var id, which is usually the header dst, but for RTT the header dst
            # is the session pseudo-station 0x0001 while the recipient is still the host 0x7620.
            fv = footer_var if footer_var is not None else dv
            body += fv.to_bytes(2, "big")
            fsize = 2
        pad = (-len(body)) % 16                      # 0xFF-pad the whole body to a multiple of 16
        body += b"\xff" * pad
        flags = (1 if do_zstd else 0) | (2 if establishing else 0)
        if pktid is None:
            pktid = self._next_pktid(dv)
        hdr = cryptomod.PiaHeader(dst=dv, src=sv, pktid=pktid, nonce8=os.urandom(8),
                                  flags=(pad << 4) | flags, footer=fsize)
        dg = self.crypto.encrypt(body, self.our_ip, hdr)
        dst = self.host_ip if unicast else self.broadcast
        self.t.send(dg, dst)
        self._capture("out", dg, f"{self.our_ip}:12345", f"{dst}:12345")
        self.tx_count += 1
        return dg

    def _send(self, proto, payload, *, dst_var=None, src_var=None, compress=False,
              footer=True, establishing=False, unicast=True, pktid=None, footer_var=None):
        """Single-message convenience wrapper over _send_messages (one message per datagram) - used
        for the connection handshake / RTT / a lone reliable frame. The reliable STREAM batches via
        _send_messages directly (see _drive_reliable)."""
        return self._send_messages([(proto, payload)], dst_var=dst_var, src_var=src_var,
                                   compress=compress, footer=footer, establishing=establishing,
                                   unicast=unicast, pktid=pktid, footer_var=footer_var)

    # ---- Pia Reliable sliding-window connection -----------------------------
    def _tx_reliable(self, seq, flagsA, inner):
        """Wrap one inner payload in a Reliable(10) frame and send it. The header's "lowest pending
        ack" = our send-window left edge; pure-ack (FLAGSA_CTRL) frames carry no sequence id of
        their own, so they ride the window base seq (the reference capture reuses 0xFFF0)."""
        s = RELIABLE_SEQ_START if seq is None else seq
        rel = reliable.build_reliable(s, self.rel.send_low(), inner, flagsA=flagsA)
        self._send(reliable.PROTO_RELIABLE, rel,
                   dst_var=int.from_bytes(self.host_var, "big"),
                   src_var=int.from_bytes(self.our_var, "big"),
                   compress=False, footer=True, establishing=False)

    def _tx_reliable_batch(self, batch):
        """Send a list of reliable frames as FEW datagrams as possible (<=RELIABLE_BATCH_MAX messages
        each) (observed: the reference capture packs up to 9 Reliable messages per datagram - the prime BufferIsFull
        lever). `batch` = [(seq, flagsA, inner), ...] already in wire order (retransmits, K*, T,
        ctrl-ack). All ride the host channel (dst=host_var) so they share one per-channel pktid."""
        if not batch:
            return
        msgs = []
        for seq, flagsA, inner in batch:
            s = RELIABLE_SEQ_START if seq is None else seq
            rel = reliable.build_reliable(s, self.rel.send_low(), inner, flagsA=flagsA)
            # Pia MESSAGE-flags 0x40 on standalone acks. The native client AND the Switch host set 0x40 on
            # EVERY pure-ack (msgflags); we were the only party sending acks at msgflags=0. It's "unknown" in
            # kinnay's wiki but universal on acks - the host honored our CUMULATIVE ack at 0 (its window freed
            # early) yet never fast-retransmitted a hole, so 0x40 is almost certainly the bit that tells the
            # host to act on the ack's SELECTIVE mask (SACK / fast-retransmit). The ctrl-ack is LAST in the
            # batch so its 0x40 never leaks into a later message via msgflags inheritance. Data stays at 0.
            mf = 0x40 if flagsA == reliable.FLAGSA_CTRL else None
            msgs.append((reliable.PROTO_RELIABLE, rel, mf))
        dv = int.from_bytes(self.host_var, "big")
        sv = int.from_bytes(self.our_var, "big")
        for i in range(0, len(msgs), RELIABLE_BATCH_MAX):
            self._send_messages(msgs[i:i + RELIABLE_BATCH_MAX], dst_var=dv, src_var=sv,
                                compress=False, footer=True, establishing=False)

    def _drive_reliable(self):
        """Per-VBlank Reliable traffic once Pia-connected, loss-tolerant via ReliableLink:
          1. open the stream with the metadata frame (Initialized) - itself retransmitted until acked;
          2. RETRANSMIT any unacked frame whose timer expired (the dropped INIT/block/data frames);
          3. bulk-ack host data we've received (with a gap mask);
          4. send a new emulator frame, unless the in-flight window is full (let retransmits drain).
        Without the open frame the host never starts its Reliable stream; without retransmission a
        single dropped frame stalls the whole stream (frames are known to drop)."""
        tick = self._tick            # VBlank counter, for the ack/seat cadence floors
        now_ms = self._now_ms        # the reliable layer's millisecond clock (RTO timer)
        if not self._rel_opened:
            seq = self.rel.queue(reliable.METADATA_FRAME, reliable.FLAGSA_INIT, now_ms)
            self._tx_reliable(seq, reliable.FLAGSA_INIT, reliable.METADATA_FRAME)
            self._rel_opened = True
            return                        # the stream opens with the metadata ('J') frame alone
        if self._connect_id is not None and not self._gba_conn_sent:
            # emulator RFU connect request ('C') - the host won't send its accept ('A') or start its
            # slot ('T') stream until it sees this. `connect_id` is our self-chosen id; any nonzero
            # value works.
            frame = gbaframe.build_connect(self._connect_id)
            seq = self.rel.queue(frame, reliable.FLAGSA_GBA, now_ms)
            self._tx_reliable(seq, reliable.FLAGSA_GBA, frame)
            self._gba_conn_sent = True
            return
        # BATCH this VBlank's whole reliable output into ONE datagram (observed: the reference capture packs up to 9
        # messages/datagram; one-datagram-per-frame was the prime BufferIsFull cause). Wire order
        # (reference capture's dominant KT/KTA): retransmits, then new K* (mid 1..n), then the T slot, then the
        # ctrl-ack LAST. Everything shares the host channel so it rides one per-channel pktid.
        batch = []
        # 1. retransmits. BLOCK/TRADE phase: GAP-TARGETED (limit=RTX_GAP_LIMIT) - re-send only the oldest
        #    unacked frame (the cumulative gap); the host buffers out-of-order so delivering the gap drains
        #    its whole run. This kills the high-RTT Go-Back-N flood (re-sending the whole window on the
        #    ~440ms-2s-RTT bridge re-sent every frame many times before its ack -> flood -> latency climbs).
        #    NI/SEAT phase (low-volume, all frames critical): whole-window (limit=None, capped at the batch)
        #    so our few NI/standby frames get through fast - gap-targeting there starved the send-NI.
        #    due_retransmits returns the ORIGINAL bytes (a retransmitted K keeps its original mid).
        in_block_phase = self._gba_accepted and not getattr(self.engine, "in_seat_phase", True)
        rtx_limit = RTX_GAP_LIMIT if in_block_phase else RTX_GAP_LIMIT_NI   # never None
        for seq, flagsA, inner in self.rel.due_retransmits(now_ms, limit=rtx_limit)[:RELIABLE_BATCH_MAX]:
            batch.append((seq, flagsA, inner))
        # FREE-RUN emission: emit ONE new 'T' slot per VBlank on our OWN clock (not gated on how many host
        # polls arrived this tick), window-bounded, plus K-acks up to a small per-VBlank cap. _gba_frame()
        # returns the phase-correct slot (NI sub-frame / block fragment / trade slot / idle keepalive) or
        # None (recv-NI quiet / nothing to send), so one call per VBlank covers every phase. The flood guard
        # is the send window (max_inflight) + the RTT-driven gap-targeted retransmit, not response pacing.
        # 2. K-acks FIRST (wire order K-then-T): at most one per VBlank for the newest owed host ts,
        #    under the K in-flight cap, leaving window slots for the 'T'. _k_seqs tracks our unacked K
        #    so a K burst can never starve the critical per-poll T (recv-NI ack / UNI slot).
        self._k_seqs.intersection_update(self.rel.unacked)   # drop K seqs the host has acked (drained)
        queued = 0
        k_frames = []
        # ONE K per VBlank, carrying the NEWEST owed host ts and the RUNNING host-'T' receive count;
        # anything older was superseded on receive. Superseding drops a K frame, never a count: _k_seq
        # was already advanced on receipt, so the K that does go out reports everything the dropped
        # ones would have. It is NOT window-gated: the console blocks its whole post-finalize sequence
        # on this ack (K_INFLIGHT_MAX above), and one superseding frame per VBlank cannot flood.
        if (self._pending_k_ts is not None
                and len(self._k_seqs) < K_INFLIGHT_MAX):
            kf = gbaframe.build_k(self._k_seq, 1, self._pending_k_ts)
            seq = self.rel.queue(kf, reliable.FLAGSA_GBA, now_ms)
            self._k_seqs.add(seq)
            k_frames.append((seq, reliable.FLAGSA_GBA, kf))
            self._pending_k_ts = None
            self.k_out += 1
            queued = 1
        # 3. our own 'T' slot - ONE per VBlank, ONLY after the host ACCEPTS our connect ('A'), window-bounded.
        t_frames = []
        if self._gba_accepted:
            # Gate on OUTSTANDING (frames the host has not acked), not on inflight(): a frame the
            # host has already acked but that is still buffered behind an older hole is on the host
            # already and must not cost us send capacity. Charging it froze the child's slot stream
            # for seconds at a time on hardware.
            #
            # The window is a CONGESTION cap and it yields to the console's liveness bound: once we
            # have been quiet for CHILD_SILENCE_LIMIT VBlanks the slot goes out regardless, because a
            # full window only costs throughput while silence costs the link (MC_TimerCount above).
            # The override is self-limiting - at most one extra frame per CHILD_SILENCE_LIMIT VBlanks.
            _out = self.rel.outstanding()
            _quiet = self._tick - self._last_t_tick >= CHILD_SILENCE_LIMIT
            _starved = _quiet and _out < self.rel.max_inflight * SILENCE_OVERRIDE_CEIL
            # Two independent gates: the congestion window, and the poll credit. The credit stops us
            # out-running a host that has slowed down; the quiet floor overrides both, so a paused
            # host can never make us go silent.
            # NOTHING exempts a slot from the credit pacer - not even a block mid-transfer. The
            # parent samples exactly ONE child slot per poll, and every non-idle slot must carry the
            # next childSendCmdId in sequence; slots it never samples are lost tag increments, and
            # after >4 of those it hard-errors [link_rfu_2.c:884-888, and rfu.SlotBuilder]. Measured
            # (j34): a bounded 17-fragment burst was echoed back as fragment 0 then fragment 9 - the
            # parent saw two of seventeen - and it stopped transmitting at the instant the burst ended.
            # Out-running the parent does not merely waste bandwidth here, it faults the console.
            # NOTHING is exempt from the credit pacer, the seat walk included. The child's cadence is
            # ONE SLOT PER POLL RECEIVED - that is the same rule the leader follows (host_trade emits
            # one held-key per VBlank because as the PARENT it owns the clock; the child's equivalent
            # is per poll, not per VBlank). Every non-idle slot advances the rolling childSendCmdId,
            # and slots the parent never samples are lost tag increments - it hard-errors after >4
            # [link_rfu_2.c:884-888]. Measured (j43): exempting the walk let it free-run at 57/s
            # uncorrelated with the console's polls; the console stopped transmitting after exactly
            # FIVE of our slots, 54ms BEFORE our first movement key. It had been polling at 55/s right
            # up to that point - credit-paced we would have matched it and walked the 145-frame route
            # in ~2.6s.
            _gated = ((_out >= self.rel.max_inflight and not _starved)
                      or (self._slot_credit <= 0 and not _quiet))
            if _starved and _out >= self.rel.max_inflight:
                self.silence_forced += 1
            inner = None
            if not _gated:
                inner = self._gba_frame()
                if inner is not None:
                    if self._slot_credit > 0:
                        self._slot_credit -= 1
                    self._last_seat_emit = tick
                    seq = self.rel.queue(inner, reliable.FLAGSA_GBA, now_ms)
                    t_frames.append((seq, reliable.FLAGSA_GBA, inner))
                    self.t_out += 1
                    self.max_silence = max(self.max_silence, self._tick - self._last_t_tick)
                    self._last_t_tick = self._tick
                    if self._emitted_ni_ack is not None:   # recv-NI ack just queued -> track the one in flight
                        self._ni_ack_seq = seq
                        self._ni_ack_bytes = self._emitted_ni_ack
            else:
                # WINDOW-GATED: cannot emit a new slot, but an in-flight block send must still advance
                # HOLD -> DONE on the host's reflection (arrives via IN frames, idempotent).
                self.engine.poll_send_done()
        # wire order is retransmits, K, T (the reference capture's KT pattern); the ctrl-ack goes last below.
        batch.extend(k_frames)
        batch.extend(t_frames)
        if self._gba_accepted and self._dbg is not None:   # per-VBlank emission trace (debug-only)
            _snd = getattr(self.engine, "sender", None)
            self._dbg.append({"tick": tick, "credits": 0, "kacks": queued,
                              "gba_emitted": len(t_frames), "inflight": self.rel.inflight(),
                              "sender": (_snd.state, _snd.index, _snd.count) if _snd else None})
        # 4. bulk-ack LAST (reference capture order K-T-A). Pure ack (FLAGSA_CTRL): carries recv_next (the contiguous gap)
        #    + the selective mask. RATE-LIMITED to ACK_PERIOD (~8.5/s, the real client's rate) and emitted ONLY
        #    when one is owed (received host data) or we have a gap to NACK - so it PIGGYBACKS on a data datagram
        #    when we're already sending one, and goes standalone only at the floor. (Root-cause fix, measured:
        #    the old `if batch or _ack_owed or due` emitted a STANDALONE pure-ack datagram nearly every VBlank
        #    (~30/s, 95% of OUT datagrams) -> half-duplex flood -> host->us return collapsed to ~9/s -> send->ack
        #    RTT 1.8s vs the real client's 24ms on the SAME bridge -> 6-frame window pushed ~3/s -> block crawl.)
        due = (tick - self._last_ack_tick) >= ACK_PERIOD
        if due and (self._ack_owed or self.rel.recv_ooo):
            batch.append((None, reliable.FLAGSA_CTRL, self.rel.ack_payload()))
            self._ack_owed = False
            self._last_ack_tick = tick
        self._tx_reliable_batch(batch)

    def _ensure_ni(self):
        """Build the NI sender once we have an identity (after the host accepts our 'C'). The 26-byte
        NI src is the child's RfuGameData connection config, CONSTRUCTED from our sim identity (the
        engine's LinkPlayer: version, public OT id, OT name) - not hardcoded reference-capture bytes."""
        if self._ni_built:
            return
        self._ni_built = True
        lp = getattr(self.engine, "lp", None) or linkplayer.LinkPlayer()
        src = ni.build_game_data(version_low=lp.version & 0xFF,
                                 trainer_id=lp.trainer_id & 0xFFFF, ot_name=lp.name)
        self._ni = ni.NISender(src)

    def _gba_frame(self):
        """Build this VBlank's emulator 'T' (0x54) frame, emitting ONE slot:

          1. NI handshake (after the host's 'A', BEFORE any UNI): drive the librfu NI sender one
             sub-frame per VBlank (game-data delivery) until it is exhausted.
          2. UNI trade slot: rfu.uni_slot(SlotBuilder.build(engine.tick())) wrapped in the child UNI
             LLSF - the trade engine's work, an all-zero IDLE slot, or (in the overworld/SEAT phase,
             ONLY AFTER establishment) a 0xBE00 held-keys keepalive.

        The held-keys gate is the C2 fix: held keys + sit() fire ONLY while engine.established
        (gReceivedRemoteLinkPlayers: both LinkPlayer blocks exchanged) AND engine.in_seat_phase (still
        in the overworld/cable seat, before the trade menu). Pre-establishment idle VBlanks are bare
        all-zero IDLE slots (tag untouched), so our tagged 0xBE00 never races ahead of the NI/block
        handshake and faults the host's childSendCmdId check. Held keys never override a real
        block/LINKCMD slot (we ask the engine first; held keys take an IDLE slot only).

        The ts (body[0:4]) is the per-NEW-frame u32 counter (+1 per new T; reused on retransmit, which
        re-offers the already-built bytes). Single slot per frame, one frame per VBlank (free-run)."""
        self._emitted_ni_ack = None      # cleared each call; set only when this call returns a recv-NI ack
        # NI handshake first (only while connected to the host's RFU, before steady UNI). The post-'A'
        # order is: our SEND-NI (game data) -> recv-NI (ack the host's own NI) -> UNI. We do NOT go UNI
        # until BOTH our send-NI is finished AND the host itself has entered UNI (its first state-4 poll);
        # going UNI early races a UNI slot ahead of the host's still-open NI sender and faults the link.
        if self.conn is not None and self._gba_accepted and not self._ni_done:
            self._ensure_ni()
            # 1. drive our send-NI to completion first (one sub-frame per VBlank). Single pass - Pia
            #    Reliable guarantees delivery+order under us, so we don't stop-and-wait.
            if not self._ni.done:
                # Stop-and-wait (see _ni_awaiting): emit the next sub-frame only once the host has
                # acked the one before it. _host_ni_ack_key carries the (state, n, phase) named by
                # the host's most recent ack of OUR NI.
                if self._ni_awaiting is None or self._host_ni_ack_key == self._ni_awaiting:
                    slot = self._ni.next_slot()
                    if slot is not None:
                        self._ni_awaiting = self._ni.emitted[-1][:3]
                        self._ni_wait_ticks = 0
                        return self._wrap_t(slot)
                else:
                    # Still unacknowledged: re-send THIS sub-frame on the paced timer. Falls through
                    # rather than returning, so the recv-NI ack below is never starved.
                    self._ni_wait_ticks += 1
                    if self._ni_wait_ticks % NI_ACK_WAIT_RESEND == 0:
                        return self._wrap_t(self._ni.emitted[-1][3])
            # 1b. our send-NI is finished, but if the host is STILL acking NI_END it never
            #     registered our NULL terminator, so it will re-ack forever and then drop the link
            #     (observed: 328 NI_END acks over ~11s, then close). The sender is single-pass on the
            #     assumption that "Pia Reliable guarantees delivery"; the same capture showed 116
            #     retransmitted seqs, so that assumption does not hold at the librfu layer. Re-emit
            #     the terminator until the host advances. Bounded so a genuinely dead host still ends.
            # 1b. Ack the host's CURRENT NI sub-frame FIRST, once per DISTINCT sub-frame
            #     (idempotent - the host needs only its current one acked). This outranks our own
            #     re-sends below because the host is BLOCKED on it and because a branch here returns
            #     early: with the order reversed, a fast re-send starves this ack entirely.
            if self._cur_ni_ack is not None and self._ni_ack_bytes != self._cur_ni_ack:
                self._emitted_ni_ack = self._cur_ni_ack
                return self._wrap_t(self._cur_ni_ack)
            # 2. Our send-NI is finished but the host is still re-acking one of our sub-frames, so
            #    the NEXT one never reached it. The sender is single-pass on the assumption that
            #    "Pia Reliable guarantees delivery"; hardware captures disprove that (105-160
            #    duplicate deliveries per run, and the host re-acking one sub-frame 356 times over
            #    6s before dropping the link). Re-send the one it waits for, PACED - see the
            #    constants above for why the rate must not be raised.
            if (self._ni.done and not self._host_uni_seen
                    and self._host_ni_resend is not None
                    and self._null_reemits < NULL_REEMIT_MAX):
                self._null_ticks += 1
                if self._null_ticks % NULL_REEMIT_EVERY == 0:
                    self._null_reemits += 1
                    if self._null_reemits == 1:
                        self.info("Host is still awaiting one of our NI sub-frames; re-sending it.")
                    return self._wrap_t(self._host_ni_resend)
            # 3. switch to UNI only once the host itself has entered UNI (_host_uni_seen); switching earlier
            #    sends a state-4 slot into the host's still-open NI sender -> the in-game Communication error.
            if not self._host_uni_seen:
                # ...but do not go silent past the console's MC_Timer budget while we wait. Re-emit
                # the ack for the host's CURRENT NI sub-frame: it is exactly what the host is blocked
                # on, it is idempotent, and a FRESH reliable frame is the only way to re-deliver it
                # (a Pia retransmit carries the same seq, which the host's reliable layer discards, so
                # it never reaches librfu). Not after the host's NULL: re-emitting the stale NI_END
                # ack through the join-textbox gap is a known cause of the in-game Communication
                # error, and the host is not polling for an ack there, so silence is correct then.
                if (self._cur_ni_ack is not None and not self._host_ni_null_seen
                        and self._tick - self._last_t_tick >= CHILD_SILENCE_LIMIT):
                    self.silence_forced += 1
                    self._emitted_ni_ack = self._cur_ni_ack
                    return self._wrap_t(self._cur_ni_ack)
                return None
            self._ni_done = True
            self.log("[sim] host entered UNI -> NI handshake complete, switching to UNI trade slots")
            self.info("Join handshake complete.")

        # engine.tick() returns the 7-int slot, OR None on a barrier frame whose want_emit() has
        # nothing to emit this VBlank (e.g. the post-trade save chain idling between echoes). None == an
        # IDLE slot here, so coerce to [0]*7 rather than crashing on words[0] (observed: post-commit crash).
        words = self.engine.tick() or [0] * 7
        if (self.linkstate is not None and (words[0] & 0xFFFF) == 0
                and getattr(self.engine, "established", False)
                and getattr(self.engine, "host_in_seat", False)
                and getattr(self.engine, "held_keys_active",
                            getattr(self.engine, "in_seat_phase", True))):
            # held-keys keepalive + sit, ONLY once the host is at its seat (host_in_seat) AND we are still
            # in the seat phase (before the party exchange latches seat_phase_over) (seat-barrier).
            words = self.linkstate.tick()
        cmd14 = self.slot.build(words)
        return self._wrap_t(rfu.uni_slot(cmd14))

    def _wrap_t(self, slot):
        """Wrap one complete slot (NI sub-frame or rfu.uni_slot(...)) in a child 'T' frame with the
        next u32 ts, advancing the counter (+1 per NEW frame)."""
        frame = gbaframe.wrap_t(slot, self.ts)
        self.ts = (self.ts + 1) & 0xFFFFFFFF
        return frame

    def _reliable_trade_payload(self):
        """Offline (conn=None) path: build ONE Reliable frame carrying this VBlank's gba 'T'. The K-ack
        layer / NI handshake are live-only (driven by the host's RFU which the offline ReplayTransport
        does not provide an 'A' for), so this stays the bare UNI/idle 'T' the offline tests expect."""
        frame = self._gba_frame()
        rel = reliable.build_reliable(self.out_seq, self.last_in_seq, frame)
        self.out_seq = (self.out_seq + 1) & 0xFFFF
        return rel

    # ---- one VBlank --------------------------------------------------------
    def tick(self):
        self._tick += 1                  # drives the ReliableLink retransmit timers
        for datagram, src_ip in self.t.recv():
            self.process_datagram(datagram, src_ip)
        # Supplementary RTT source: feed any round-trips the RTT protocol measured into the reliable RTO
        # (median of the last 7), converting VBlanks->ms. Over this link the host doesn't echo our RTT
        # systime, so this is usually empty and the reliable layer's own clean-ack round-trip is what
        # actually drives the RTO; if a host does echo it, these samples fold into the same median.
        if self.conn is not None and getattr(self.conn, "rtt_samples", None):
            for rtt_vblanks in self.conn.rtt_samples:
                self.rel.add_rtt_sample(rtt_vblanks * MS_PER_VBLANK)
            self.conn.rtt_samples = []
        # S0 handshake + RTT replies; each outbox entry is a dict carrying its own stage var-ids and
        # Pia framing (compress/footer/establishing) [pia_connect].
        if self.conn:
            if hasattr(self.conn, "maybe_originate_rtt"):
                self.conn.maybe_originate_rtt(self._tick)   # liveness RTT probe (dst=0x0001)
            for e in self.conn.drain():
                self._send(e["proto"], e["payload"], dst_var=e["dst"], src_var=e["src"],
                           compress=e["compress"], footer=e["footer"],
                           establishing=e["establishing"], unicast=e.get("unicast", True),
                           pktid=e.get("pktid"), footer_var=e.get("footer_var"))
        # Reliable traffic only once the Pia connection is up. Live (conn present): drive the full
        # sliding-window connection (open stream + bulk-acks + gba frame) so the host engages its
        # own Reliable stream. Offline replay/tests (conn=None): emit the bare gba frame as before.
        if self.connected:
            if self.conn is not None:
                self._drive_reliable()
            else:
                self._send(reliable.PROTO_RELIABLE, self._reliable_trade_payload(),
                           dst_var=int.from_bytes(self.host_var, "big"),
                           src_var=int.from_bytes(self.our_var, "big"),
                           compress=False, footer=True, establishing=False)

    def close(self):
        if self._cap:
            self._cap.close()
