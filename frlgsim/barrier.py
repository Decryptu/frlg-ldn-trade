"""Child-initiated READY_EXIT_STANDBY (0x6600) / READY_CLOSE_LINK (0x5F00) barrier mirror [link_rfu_2.c:1471-1602].
The host's leader branch waits for the child's 0x6600 first [link_rfu_2.c:1577-1591], so a purely reactive
child deadlocks at every standby: the child must initiate. Offline, an unanswered barrier is watchdog-released."""

from . import rfu

IDLE = "IDLE"
STANDBY = "STANDBY"      # answering / initiating READY_EXIT_STANDBY (0x6600)
CLOSE = "CLOSE"          # answering / initiating READY_CLOSE_LINK (0x5F00)

# Offline watchdog for an initiated barrier with no host 0x6600; must exceed the ROM's >60-frame child
# re-emit cadence [link_rfu_2.c:1529] so a slow participating host still completes via the echo.
INITIATE_TIMEOUT = 120

# Frames without a host barrier op before a REACTIVE standby returns to IDLE; CLOSE is terminal and never auto-clears.
IDLE_TIMEOUT = 90


class BarrierResponder:
    """While a barrier is active the engine must stay quiescent: a barrier and a block never coexist on the wire
    [link_rfu_2.c:1553/1569/1586]."""

    def __init__(self, log=lambda *a: None):
        self.mode = IDLE
        self.initiated = False       # this barrier was started by our FSM (vs. reactively by the host)
        self.host_count = None       # latched from the host's last IN 0x6600/0x5F00 word1 (or None)
        self.local_count = 0         # our resendExitStandbyCount mirror (climbs +1 per completed round)
        self._since_host = 0         # frames since we last saw the host's barrier op
        self._since_initiate = 0     # frames since we INITIATEd, with no host 0x6600 yet
        self.rounds = 0              # standby rounds completed (for logging/tests)
        # Live-only bound on NEW emits per count; emitting forever keeps the host in the same round (deadlock +
        # flood). None = every VBlank (the offline MockHost has no retransmit).
        self.max_emits = None
        self._burst_for = None       # count the current burst is for
        self._burst_n = 0            # NEW frames emitted in the current burst
        self.log = log

    @property
    def active(self):
        return self.mode != IDLE

    def reset_to_idle(self):
        """Drops a STANDBY to IDLE, preserving local_count; CLOSE is terminal and is not reset."""
        if self.mode == STANDBY:
            self.mode = IDLE
            self.initiated = False
            self._since_initiate = 0
            self._burst_for = None

    def initiate(self, kind=STANDBY):
        """Idempotent while the same kind is already active."""
        if kind == CLOSE:
            if self.mode != CLOSE:
                self.mode = CLOSE
                self.initiated = True
                self._since_host = 0
                self._since_initiate = 0
                self.log(f"barrier: INITIATE close-link 0x5F00 (count={self.local_count})")
            return
        if self.mode == STANDBY:
            return
        self.mode = STANDBY
        self.initiated = True
        self.host_count = None
        self._since_host = 0
        self._since_initiate = 0
        self._burst_for = None
        self.log(f"barrier: INITIATE standby 0x6600 (local_count={self.local_count})")

    def on_in_slot(self, parsed):
        """Returns True iff this slot COMPLETED the current standby round."""
        if parsed is None:
            return False
        op = parsed.get("op")
        if op == rfu.READY_EXIT_STANDBY:
            return self._on_host_standby(parsed.get("count", 0))
        if op == rfu.READY_CLOSE_LINK:
            self._on_host_close(parsed.get("count", 0))
        return False

    def _on_host_standby(self, count):
        """Initiated: the host echoing our count passes the round. Reactive: mirror the host's count and keep
        answering; completing on the first match would stop replies while the host still waits -> deadlock."""
        self._since_host = 0
        prev_host = self.host_count
        self.host_count = count
        if self.initiated and self.mode == STANDBY:
            if count == self.local_count:
                self.local_count += 1
                self.rounds += 1
                self.mode = IDLE
                self.initiated = False
                self._since_initiate = 0
                self.log(f"barrier: child-initiated standby round complete (host echoed "
                         f"count={count}) -> local_count={self.local_count}, rounds={self.rounds}")
                return True
            return False
        # The leader re-broadcasts count=N after we completed round N; treating it as a new reactive round
        # would regress local_count and spin a spurious round.
        if count < self.local_count:
            return False
        if self.mode != STANDBY:
            self.mode = STANDBY
            self.initiated = False
            self.log(f"barrier: host 0x6600 count={count} -> STANDBY (reactive mirror)")
        elif prev_host is not None and count != prev_host:
            self.rounds += 1
            self.log(f"barrier: host advanced reactive round {prev_host}->{count}")
        self.local_count = count          # mirror so our reply matches the host's recv gate exactly
        self._since_initiate = 0
        return False

    def _on_host_close(self, count):
        self._since_host = 0
        self.host_count = count
        # Close's recv gate accepts any count [link_rfu_2.c:1175-1176]; mirroring is cosmetic.
        self.local_count = count
        if self.mode != CLOSE:
            self.mode = CLOSE
            self.initiated = False
            self.log(f"barrier: host 0x5F00 count={count} -> CLOSE (mirror reply)")

    def observe_frame(self, saw_barrier):
        """saw_barrier: this IN frame carried a host barrier op. CLOSE never times out."""
        if self.mode != STANDBY:
            return
        if saw_barrier:
            self._since_host = 0
            self._since_initiate = 0
            return
        self._since_host += 1
        if self.initiated:
            self._since_initiate += 1
            if self._since_initiate > INITIATE_TIMEOUT:
                # A watchdog release is not a real round: local_count must NOT increment
                # (resendExitStandbyCount++ only on a real completion [link_rfu_2.c:1545]) so counts stay
                # in lockstep with a host that did participate.
                self.mode = IDLE
                self.initiated = False
                self.log(f"barrier: INITIATE standby unanswered for >{INITIATE_TIMEOUT}f -> IDLE "
                         f"(watchdog release, local_count held at {self.local_count})")
        else:
            if self._since_host > IDLE_TIMEOUT:
                # The host stopped broadcasting: its final round passed (resendExitStandbyCount++
                # [link_rfu_2.c:1545]); mirror that increment.
                self.local_count += 1
                self.rounds += 1
                self.mode = IDLE
                self.log(f"barrier: host stopped 0x6600 for >{IDLE_TIMEOUT}f -> IDLE "
                         f"(final reactive round passed, local_count={self.local_count})")

    def want_emit(self):
        """Returns the 7-int pre-tag gSendCmd run for this VBlank, or None if no barrier is active."""
        if self.mode not in (STANDBY, CLOSE):
            return None
        if self.max_emits is not None:
            if self._burst_for != self.local_count:
                self._burst_for = self.local_count
                self._burst_n = 0
            if self._burst_n >= self.max_emits:
                return None
            self._burst_n += 1
        if self.mode == STANDBY:
            return rfu.exit_standby_words(self.local_count)
        return rfu.close_link_words(self.local_count)
