"""Transport adapters: ReplayTransport replays a capture's IN datagrams offline; LiveTransport joins the console's LDN
session (kinnay's ldn) and moves UDP :12345 via a bound UDP TX socket + an AF_PACKET RX socket (so subnet-directed
broadcasts are not dropped); HostTransport is the AP side. The live classes need root and a real Switch.
"""

import json
import os
import select
import socket
import struct
import subprocess
import threading
import time
import traceback
from pathlib import Path

ETH_P_IP = 0x0800
PROTO_UDP = 17
PIA_PORT = 12345


_PIA_HDR = 0x5C     # Pia 6.16-6.41 LDN system header length; the game payload follows it


def _b85_decode(s):
    """Custom base85: alphabet 0x23..0x78 skipping 0x5c, first char = least-significant digit, 4-byte LE groups."""
    out = bytearray()
    for i in range(0, len(s) - len(s) % 5, 5):
        v = 0
        for c in reversed(s[i:i + 5]):
            v = v * 85 + ((c - 0x23) if c < 0x5C else (c - 0x24))
        out += (v & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(out)


def _frlg_name(b):
    out = []
    for x in b:
        if x == 0xFF:
            break
        if 0xBB <= x <= 0xD4:
            out.append(chr(ord("A") + x - 0xBB))
        elif 0xD5 <= x <= 0xEE:
            out.append(chr(ord("a") + x - 0xD5))
        elif 0xA1 <= x <= 0xAA:
            out.append(chr(ord("0") + x - 0xA1))
        else:
            out.append(" " if x == 0 else "?")
    return "".join(out).rstrip()


def _dump_beacon(app_data, log):
    """Diagnostics only; the connect id is not taken from the beacon."""
    if not app_data:
        log("[live] beacon: NO application_data on the advertisement")
        return None
    app_data = bytes(app_data)
    log(f"[live] beacon application_data ({len(app_data)} B): {app_data.hex()}")
    if len(app_data) >= _PIA_HDR:
        gba = app_data[_PIA_HDR:]
        log(f"[live] beacon RFU payload (after the 0x5C Pia header, {len(gba)} B): {gba.hex()}")
        try:
            d = _b85_decode(gba)
            if len(d) >= 24:
                log(f"[live] beacon decoded: host name={_frlg_name(d[2:10])!r} "
                    f"TID=0x{int.from_bytes(d[0:2], 'little'):04x} "
                    f"RFU-session-id=0x{int.from_bytes(d[10:12], 'little'):04x} "
                    f"tradeSpecies={int.from_bytes(d[20:24], 'little') >> 16}")
                # The only pre-join view of the host's game state; the verbose sink is unusable on live runs, so use INFO.
                word = int.from_bytes(d[16:18], "little")
                info = getattr(log, "info", log)
                info(f"host beacon game state: activity={word & 0x007F} "
                     f"started_activity={bool(word & (1 << 15))} "
                     f"has_card={bool(word & 0x4000)} word=0x{word:04x}")
        except Exception as e:
            log(f"[live] beacon decode skipped ({type(e).__name__}: {e})")
    return app_data


def _flatten_exc(e, depth=0):
    """Flatten a (Base)ExceptionGroup (trio nursery failures) to its leaf exceptions -> [(depth, exc)]."""
    subs = getattr(e, "exceptions", None)
    if subs:
        out = []
        for sub in subs:
            out.extend(_flatten_exc(sub, depth + 1))
        return out
    return [(depth, e)]


def _format_join_error(e):
    leaves = _flatten_exc(e)
    if len(leaves) == 1 and leaves[0][1] is e:
        leaf = e
        body = "".join(traceback.format_exception(type(leaf), leaf, leaf.__traceback__))
        return f"{type(leaf).__name__}: {leaf}\n{body}"
    parts = [f"{type(e).__name__} with {len(leaves)} underlying error(s):"]
    for i, (_d, leaf) in enumerate(leaves, 1):
        body = "".join(traceback.format_exception(type(leaf), leaf, leaf.__traceback__))
        parts.append(f"  [{i}] {type(leaf).__name__}: {leaf}\n{body}")
    return "\n".join(parts)

LDN_VIFS = {"ldn", "ldn-mon", "ldn-tap", "ldnclient"}
AIR_MONITOR_VIF = "ldnair"      # passive capture vif owned by scratchpad/run_*.sh; never touched here


def _run(cmd):
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _iw_del(iface):
    _run(["iw", "dev", iface, "del"])


def _sysctl(key, val):
    _run(["sysctl", "-wq", f"{key}={val}"])


def get_power_save(iface):
    try:
        out = subprocess.check_output(["iw", "dev", iface, "get", "power_save"],
                                      text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    low = out.lower()
    if "power save: on" in low:
        return True
    if "power save: off" in low:
        return False
    return None


def disable_power_save(iface, log=print):
    """rtw88 defaults a new managed vif to power save ON; a dozing station wakes only on the console's 100 TU beacons,
    pinning the link at ~11-15 exchanges/s. An AP vif never dozes, which is why hosting never had this.
    """
    before = get_power_save(iface)
    _run(["iw", "dev", iface, "set", "power_save", "off"])
    after = get_power_save(iface)
    if after is False:
        log(f"[live] 802.11 power save on {iface}: {'on -> off' if before else 'off'}")
    else:
        log(f"[live] WARNING: could not turn 802.11 power save off on {iface} "
            f"(before={before}, after={after}); the link will run at beacon cadence")
    return after is False


def list_phy_ifaces():
    mapping, current = {}, None
    try:
        out = subprocess.check_output(["iw", "dev"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return mapping
    for raw in out.splitlines():
        s = raw.strip()
        if s.startswith("phy#"):
            current = "phy" + s[4:]
            mapping[current] = []
        elif s.startswith("Interface ") and current is not None:
            mapping[current].append(s.split()[1])
    return mapping


def free_radio(phys, log=print):
    """Delete stale LDN vifs and take other interfaces off the radio (SET_CHANNEL -> EBUSY otherwise). Needs root."""
    mapping = list_phy_ifaces()
    for phy in {p for p in phys if p}:
        for iface in mapping.get(phy, []):
            if iface == AIR_MONITOR_VIF:
                # the launchers' passive air capture, created before the host starts; leave it up
                continue
            if iface in LDN_VIFS:
                _iw_del(iface)
            else:
                _run(["nmcli", "device", "set", iface, "managed", "no"])
                _run(["ip", "link", "set", iface, "down"])
                log(f"[live] freed radio: brought {iface} ({phy}) down")
    # A failed join leaks a still-associated station vif that makes the next association fail (nl80211 status 1);
    # delete every known LDN vif by name.
    for vif in LDN_VIFS:
        if vif in {i for ifs in mapping.values() for i in ifs} or _iface_exists(vif):
            _iw_del(vif)
            _run(["ip", "link", "del", vif])
            log(f"[live] freed radio: removed stale LDN vif {vif}")
    # wpa_supplicant is not killed: the interfaces above are already unmanaged and down, and a global kill
    # would drop any other adapter's connection. If a join still fails with EBUSY, stop it by hand.
    time.sleep(0.3)


def _iface_exists(iface):
    import os
    return os.path.exists(f"/sys/class/net/{iface}")


def light_cleanup(log=print):
    for iface in sorted(LDN_VIFS):
        _iw_del(iface)
    time.sleep(0.3)


def tune_iface(iface, keep_ip, broadcast_ip, log=print):
    """Make the iface deliver the host's link-local subnet broadcasts: rp_filter off, the broadcast route in the local
    table, stray zeroconf addresses removed. Needs root.
    """
    _run(["nmcli", "device", "set", iface, "managed", "no"])
    _run(["pkill", "-f", f"avahi-autoipd.*{iface}"])
    for key in (f"net.ipv4.conf.{iface}.rp_filter", "net.ipv4.conf.all.rp_filter",
                "net.ipv4.conf.default.rp_filter"):
        _sysctl(key, "0")
    _sysctl(f"net.ipv4.conf.{iface}.accept_local", "1")
    _run(["ip", "route", "replace", "table", "local", "broadcast", broadcast_ip,
          "dev", iface, "proto", "static", "scope", "link", "src", keep_ip])
    try:
        out = subprocess.check_output(["ip", "-4", "addr", "show", "dev", iface],
                                      text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                cidr = line.split()[1]
                ip, _, prefix = cidr.partition("/")
                if ip != keep_ip and prefix != "24":
                    _run(["ip", "addr", "del", cidr, "dev", iface])
                    log(f"[live] removed stray address {cidr} from {iface}")
    except Exception as e:
        log(f"[live] stray-address cleanup skipped: {e}")

# The emulator's LDN passphrase (NintendoClients wiki "LDN Passphrases"): one 64-byte value, shared across the GBA
# emulator's titles.
GBA_APP_PASSPHRASE = bytes.fromhex(
    "fcb6f6adb9dfea66aca9c326149d2b3b08a781895cbf78f720d78b85a57584a9"
    "9665d237797b2a41ddef14063ec28d259143af7832fb3cbcf2759cbfbdc81d8c")
assert len(GBA_APP_PASSPHRASE) == 64


class ReplayTransport:
    def __init__(self, in_datagrams, our_ip="169.254.21.2", host_ip="169.254.21.1"):
        self._in = list(in_datagrams)
        self._i = 0
        self.our_ip = our_ip
        self.host_ip = host_ip
        self.sent = []
        self.batch = 4

    def recv(self):
        out = []
        for _ in range(self.batch):
            if self._i >= len(self._in):
                break
            out.append(self._in[self._i])
            self._i += 1
        return out

    def send(self, datagram, dst_ip):
        self.sent.append((datagram, dst_ip))

    @property
    def drained(self):
        return self._i >= len(self._in)

    @classmethod
    def from_capture(cls, raw_path):
        metas, ins = [], []
        sess = {}
        for line in open(raw_path, errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("rec") == "meta":
                if r.get("event") == "session":
                    sess = r
                continue
            if r.get("rec") == "pkt" and r.get("dir") == "in":
                ins.append((bytes.fromhex(r["hex"]), r["src"].rsplit(":", 1)[0]))
        t = cls(ins, our_ip=sess.get("ip", "169.254.21.2"),
                host_ip=sess.get("ip", "169.254.21.1").rsplit(".", 1)[0] + ".1")
        t.ssid = bytes.fromhex(sess["ssid_hex"]) if sess.get("ssid_hex") else None
        return t


class LiveTransport:
    LOCAL_COMMUNICATION_ID = 0x0100610011000000
    SCENE_ID = 0
    APPLICATION_VERSION = 88

    def __init__(self, password=None, nickname="EMU", keys_path="~/.switch/prod.keys",
                 local_comm_id=None, scene_id=None, app_version=None,
                 phyname="phy0", ifname="ldnclient", log=print,
                 scan_channels=(1, 6, 11), scan_dwell=0.6):
        self.info = getattr(log, "info", log)
        self.password = password if password else GBA_APP_PASSPHRASE
        self.nickname = nickname
        self.keys_path = keys_path
        self.phyname = phyname
        self.ifname = ifname
        self.scan_channels = tuple(scan_channels)
        self.scan_dwell = scan_dwell
        if local_comm_id is not None:
            self.LOCAL_COMMUNICATION_ID = local_comm_id
        if scene_id is not None:
            self.SCENE_ID = scene_id
        if app_version is not None:
            self.APPLICATION_VERSION = app_version
        self.log = log
        self.ssid = None
        self.our_ip = None
        self.host_ip = None
        self.our_mac = None
        self.host_mac = None
        self.app_data = None
        self.iface = None
        self.broadcast = None
        self._tx = None
        self._rx = None
        self._rx_seen = 0
        self._thread = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._err = None

    def start(self, timeout=30, attempts=3, settle=1.5):
        """Join, retrying: the LDN/nl80211 layer flakes intermittently (radio busy, association timeout, a stale vif)."""
        last_err = None
        for attempt in range(1, attempts + 1):
            free_radio({self.phyname}, self.log)
            self._err = None
            self._ready.clear()
            self._stop.clear()
            self._thread = threading.Thread(target=self._run_ldn, daemon=True)
            self._thread.start()
            if not self._ready.wait(timeout):
                last_err = f"LDN join timed out after {timeout}s (attempt {attempt}/{attempts})"
                self.log(f"[live] {last_err}")
                self._stop.set()
            elif self._err:
                last_err = self._err
            else:
                tune_iface(self.iface, self.our_ip, self.broadcast, self.log)
                disable_power_save(self.iface, self.info)
                self._setup_sockets()
                if attempt > 1:
                    self.log(f"[live] LDN join succeeded on attempt {attempt}/{attempts}.")
                return self
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=2)
            if attempt < attempts:
                self.log(f"[live] retrying LDN join in {settle}s "
                         f"(attempt {attempt + 1}/{attempts})...")
                time.sleep(settle)
        light_cleanup(self.log)
        raise RuntimeError(f"LDN join failed after {attempts} attempt(s):\n{last_err}")

    def _run_ldn(self):
        try:
            import trio
            import ldn
        except ImportError as e:                     # pragma: no cover
            self._err = f"missing dep for live mode: {e}"
            self._ready.set()
            return

        async def main():
            keys = ldn.load_keys(self.keys_path)
            self.info("Scanning for the FRLG network...")
            # A Switch beacons every ~102ms; ldn.scan's default 110ms dwell sees barely one beacon per channel and misses the network.
            networks = await ldn.scan(keys, phyname=self.phyname,
                                      channels=list(self.scan_channels),
                                      dwell_time=self.scan_dwell)
            joinable = [n for n in networks
                        if n.accept_policy != ldn.ACCEPT_NONE
                        and n.num_participants < n.max_participants]
            for n in networks:
                self.log(f"[live] saw network comm_id=0x{n.local_communication_id:016x} "
                         f"scene={n.scene_id} app_version={n.app_version} s{n.num_participants}/{n.max_participants} "
                         f"accept_policy={getattr(n, 'accept_policy', '?')}")
            net = next((n for n in joinable
                        if n.local_communication_id == self.LOCAL_COMMUNICATION_ID), None)
            if net is None and len(joinable) == 1:
                net = joinable[0]
                self.log(f"[live] no comm-id match; using the only joinable network "
                         f"(comm_id=0x{net.local_communication_id:016x})")
            if net is None:
                self._err = (f"no joinable FRLG network (saw {len(networks)}, "
                             f"{len(joinable)} joinable) - set --comm-id from the list above")
                self._ready.set()
                return
            self.LOCAL_COMMUNICATION_ID = net.local_communication_id
            self.app_data = _dump_beacon(getattr(net, "application_data", b"") or b"", self.log)
            param = ldn.ConnectNetworkParam()
            param.keys = keys
            param.network = net
            param.password = self.password
            param.name = self.nickname.encode()
            param.app_version = self.APPLICATION_VERSION
            param.phyname = self.phyname
            param.ifname = self.ifname
            self.info("Joining the host...")
            async with ldn.connect(param) as network:
                info = network.info()
                self.ssid = info.ssid
                self.iface = self.ifname
                # The host is participant 0; its IP fixes the 169.254.X subnet.
                parts = list(getattr(info, "participants", []) or [])
                host = parts[0] if parts else None
                self.host_ip = host.ip_address if host else "169.254.21.1"
                self.host_mac = bytes(host.mac_address) if host else b"\x00" * 6
                ours = next((p for p in parts if p is not host and self._pname(p) == self.nickname),
                            None) or next((p for p in parts if p is not host
                                           and getattr(p, "connected", False)), None)
                self.our_ip = (self._iface_ip() or (ours.ip_address if ours else None)
                               or self.host_ip.rsplit(".", 1)[0] + ".2")
                self.our_mac = ((bytes(ours.mac_address) if ours else None)
                                or self._iface_mac() or b"\x00" * 6)
                self.broadcast = self.our_ip.rsplit(".", 1)[0] + ".255"
                self.log(f"[live] joined ssid={self.ssid.hex()} "
                         f"us={self.our_ip}/{self.our_mac.hex()} "
                         f"host={self.host_ip}/{self.host_mac.hex()}")
                self.info("Joined.")
                self._ready.set()
                while not self._stop.is_set():
                    await trio.sleep(0.2)

        try:
            trio.run(main)
        except BaseException as e:                     # pragma: no cover
            self._err = _format_join_error(e)
            self.log(f"[live] LDN join FAILED:\n{self._err}")
            self._ready.set()

    @staticmethod
    def _pname(p):
        try:
            return p.name.decode("utf-8", "replace").rstrip("\0")
        except Exception:
            return ""

    def _iface_mac(self):
        try:
            with open(f"/sys/class/net/{self.ifname}/address") as f:
                return bytes.fromhex(f.read().strip().replace(":", ""))
        except OSError:
            return None

    def _iface_ip(self):
        try:
            out = subprocess.check_output(["ip", "-4", "-o", "addr", "show", "dev", self.ifname],
                                          text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                parts = line.split()
                if "inet" in parts:
                    ip = parts[parts.index("inet") + 1].split("/")[0]
                    if ip.startswith("169.254."):
                        return ip
        except Exception:
            pass
        return None

    def _setup_sockets(self):
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        tx.setblocking(False)             # never block the frame loop
        tx.bind(("0.0.0.0", PIA_PORT))
        self._tx = tx
        rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_IP))
        rx.bind((self.iface, 0))
        rx.setblocking(False)
        # AF_PACKET ring overflow between ~60Hz drains shows up as silent gaps; the kernel clamps to net.core.rmem_max.
        try:
            rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
            got = rx.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
            self.log(f"[live] rx socket SO_RCVBUF = {got} bytes "
                     f"(raise net.core.rmem_max if lower than requested 8 MiB)")
        except OSError as e:
            self.log(f"[live] could not enlarge rx SO_RCVBUF: {e}")
        self._rx = rx
        self._pinned_neighbours = set()

    def send(self, datagram, dst_ip):
        dst = self.broadcast if dst_ip in (self.broadcast, "255.255.255.255") else dst_ip
        try:
            self._tx.sendto(datagram, (dst, PIA_PORT))
        except OSError as e:
            self.log(f"[live] sendto failed: {e}")

    def _accept_dst(self, dst_ip):
        """The host broadcasts its Net 0x11 to the subnet .255 before unicasting; accept any 169.254.*.255 and the global broadcast."""
        return (dst_ip == self.our_ip
                or (dst_ip.startswith("169.254.") and dst_ip.endswith(".255"))
                or dst_ip in ("255.255.255.255",))

    def recv(self):
        out = []
        if self._rx is None:
            return out
        while True:
            try:
                data = self._rx.recv(65535)
            except (BlockingIOError, OSError):
                break
            parsed = self._parse_udp(data)
            if parsed is None:
                continue
            src_ip, src_port, dst_ip, dst_port, payload = parsed
            if src_ip == self.our_ip or dst_port != PIA_PORT or not self._accept_dst(dst_ip):
                if dst_port == PIA_PORT and src_ip != self.our_ip:
                    self._rx_filtered = getattr(self, "_rx_filtered", 0) + 1
                    if self._rx_filtered <= 12:
                        self.log(f"[live] RX FILTERED #{self._rx_filtered}: {src_ip} -> "
                                 f"{dst_ip}:{dst_port} len={len(payload)} "
                                 f"(our_ip={self.our_ip}) {payload[:4].hex()}")
                continue
            self._rx_seen += 1
            if self._rx_seen <= 10:
                self.log(f"[live] RX #{self._rx_seen}: {src_ip} -> {dst_ip}:{dst_port} "
                         f"len={len(payload)} {payload[:4].hex()}")
            out.append((payload, src_ip))
        return out

    @staticmethod
    def _parse_udp(frame):
        if len(frame) < 14 + 20 + 8 or struct.unpack_from("!H", frame, 12)[0] != ETH_P_IP:
            return None
        ip = frame[14:]
        if (ip[0] >> 4) != 4 or ip[9] != PROTO_UDP:
            return None
        ihl = (ip[0] & 0x0F) * 4
        src_ip = socket.inet_ntoa(ip[12:16])
        dst_ip = socket.inet_ntoa(ip[16:20])
        udp = ip[ihl:]
        if len(udp) < 8:
            return None
        src_port, dst_port, ulen = struct.unpack_from("!HHH", udp, 0)
        payload = udp[8:][:max(0, ulen - 8)] if ulen >= 8 else udp[8:]
        return src_ip, src_port, dst_ip, dst_port, payload

    def stop(self):
        self._stop.set()
        for s in (self._tx, self._rx):
            try:
                if s:
                    s.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        light_cleanup(self.log)


def _parse_iw_modes(iw_phy_output):
    modes, soft, section = [], [], None
    for raw in iw_phy_output.splitlines():
        s = raw.strip()
        if s.startswith("Supported interface modes:"):
            section = "modes"
        elif s.startswith("software interface modes"):
            section = "soft"
        elif s.startswith("* ") and section:
            (modes if section == "modes" else soft).append(s[2:].strip())
        elif section and s and not s.startswith("* "):
            section = None
    return modes, soft


def list_phys():
    import os
    try:
        return sorted(os.listdir("/sys/class/ieee80211"))
    except OSError:
        return []


def find_ap_phy(log=print):
    """First phy advertising AP mode (for `--phy auto`; phy numbering changes when the adapter is reloaded)."""
    for phy in list_phys():
        try:
            out = subprocess.check_output(["iw", "phy", phy, "info"],
                                          text=True, stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        modes, _soft = _parse_iw_modes(out)
        if "AP" in modes:
            log(f"[host] --phy auto -> {phy} (AP-capable)")
            return phy
    return None


HOST_WIFI_PROFILES = {
    "mt76x0u": ("ALFA AWUS036ACHM", True, False),
    "rtw88_8822bu": ("TP-Link Archer T3U (USB 2357:012d)", True, True),
}

# Match the USB id as well as the driver so the Pi's internal radio cannot be selected because it became phy0.
HOST_ADAPTER_PROFILES = {
    "tplink-archer-t3u": {
        "label": "TP-Link Archer T3U / AC1300",
        "driver": "rtw88_8822bu",
        "usb_id": "2357:012d",
    },
}


def _phy_driver(phyname):
    try:
        return os.path.basename(os.path.realpath(
            f"/sys/class/ieee80211/{phyname}/device/driver")) or "?"
    except OSError:
        return "?"


def _phy_usb_id(phyname):
    try:
        node = Path(f"/sys/class/ieee80211/{phyname}/device").resolve()
    except OSError:
        return None
    for candidate in (node, *node.parents):
        try:
            vendor = (candidate / "idVendor").read_text(encoding="ascii").strip()
            product = (candidate / "idProduct").read_text(encoding="ascii").strip()
        except OSError:
            continue
        if vendor and product:
            return f"{vendor.lower()}:{product.lower()}"
    return None


def describe_phys():
    return [
        (phy, _phy_driver(phy), _phy_usb_id(phy))
        for phy in list_phys()
    ]


def find_adapter_phy(adapter, log=print):
    """Refuses to guess: a missing or duplicated adapter raises; a literal phyN via --phy is handled by the caller."""
    profile = HOST_ADAPTER_PROFILES.get(adapter)
    if profile is None:
        choices = ", ".join(sorted(HOST_ADAPTER_PROFILES))
        raise RuntimeError(
            f"unknown Wi-Fi adapter profile {adapter!r}; choose one of: {choices}")
    matches = [
        phy for phy, driver, usb_id in describe_phys()
        if driver == profile["driver"] and usb_id == profile["usb_id"]
    ]
    if len(matches) == 1:
        phy = matches[0]
        log(f"[host] adapter {adapter} -> {phy} "
            f"({profile['driver']}, USB {profile['usb_id']})")
        return phy
    visible = ", ".join(
        f"{phy} ({driver}, USB {usb_id or '?'})"
        for phy, driver, usb_id in describe_phys()) or "none"
    if not matches:
        raise RuntimeError(
            f"adapter {profile['label']} was not found "
            f"(need {profile['driver']}, USB {profile['usb_id']}); "
            f"visible PHYs: {visible}. Pass --phy phyN to select a PHY explicitly.")
    raise RuntimeError(
        f"adapter {profile['label']} is ambiguous ({', '.join(matches)}); "
        "unplug one matching adapter or pass --phy phyN explicitly.")


def wifi_profile_messages(driver, skip_encryption, accept_decrypted_ccmp):
    profile = HOST_WIFI_PROFILES.get(driver)
    if profile is None:
        return []
    name, expected_skip, expected_accept = profile
    expected = (
        f"--{'skip' if expected_skip else 'no-skip'}-encryption "
        f"--{'accept' if expected_accept else 'no-accept'}-decrypted-ccmp"
    )
    messages = [f"Wi-Fi adapter profile: {name} ({driver}); expected {expected}."]
    if (bool(skip_encryption), bool(accept_decrypted_ccmp)) != \
            (expected_skip, expected_accept):
        messages.append(
            "WARNING: selected Wi-Fi compatibility flags do not match the "
            f"hardware-proven {name} profile.")
    return messages


def preflight_host(phyname, log=print, _iw_output=None):
    """`iw phy` 'Supported interface modes' is the driver's registered capability, not a setting (MT7601U: managed+monitor
    only -> IFTYPE_AP is EOPNOTSUPP). Raises RuntimeError with the verdict; `_iw_output` injects canned output for tests.
    """
    if _iw_output is None:
        try:
            _iw_output = subprocess.check_output(["iw", "phy", phyname, "info"],
                                                 text=True, stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            log(f"[host] preflight: could not run `iw phy {phyname} info` ({e}); "
                f"skipping the AP-mode check")
            return True
    modes, soft = _parse_iw_modes(_iw_output)
    driver = _phy_driver(phyname)
    if "AP" in modes:
        if "monitor" not in modes and "monitor" not in soft:
            log(f"[host] preflight: {phyname} ({driver}) has AP but no monitor mode - "
                f"advertisement TX may fail (LDN needs an AP + monitor vif pair)")
        log(f"[host] preflight OK: {phyname} ({driver}) supports AP mode "
            f"(modes: {', '.join(modes)})")
        return True
    raise RuntimeError(
        f"{phyname} ({driver}) cannot host: driver registers only "
        f"[{', '.join(modes) or 'nothing'}] - no AP mode. This is a driver capability, not a "
        f"setting. Use an AP-capable adapter (mt76 family: AWUS036ACM/mt7612u, AWUS036ACHM/mt7610u) "
        f"and verify with `iw phy <phy> info` -> '* AP' under Supported interface modes.")


class HostTransport:
    # comm_id/scene captured from a real FRLG session; the console's scan filters on comm_id, so a placeholder makes us invisible.
    LOCAL_COMMUNICATION_ID = 0x01006fa0233f8000
    SCENE_ID = 22287
    APPLICATION_VERSION = 88

    def __init__(self, app_data=b"", password=None, nickname="EMU", keys_path="~/.switch/prod.keys",
                 local_comm_id=None, scene_id=None, app_version=None, max_participants=2,
                 phyname="phy0", ifname="ldn-tap", ap_ifname="ldn", mon_ifname="ldn-mon",
                 channel=None, skip_encryption=False, accept_decrypted_ccmp=False,
                 tracer=None, log=print):
        self.info = getattr(log, "info", log)
        self.tracer = tracer
        self.app_data = bytes(app_data or b"")
        self.password = password if password else GBA_APP_PASSPHRASE
        self.nickname = nickname
        self.keys_path = keys_path
        self.max_participants = max_participants
        self.phyname = phyname
        self.ifname = ifname
        self.ap_ifname = ap_ifname
        self.mon_ifname = mon_ifname
        self.channel = channel
        self.skip_encryption = skip_encryption
        self.accept_decrypted_ccmp = accept_decrypted_ccmp
        if local_comm_id is not None:
            self.LOCAL_COMMUNICATION_ID = local_comm_id
        if scene_id is not None:
            self.SCENE_ID = scene_id
        if app_version is not None:
            self.APPLICATION_VERSION = app_version
        self.log = log
        self.ssid = None
        self.our_ip = None
        self.host_ip = None
        self.our_mac = None
        self.broadcast = None
        self.iface = None
        self.participants = []
        self.join_events = 0
        self._network = None
        self._tx = None
        self._rx = None
        self._rx_seen = 0
        self._thread = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._err = None

    def start(self, timeout=30, attempts=3, settle=1.5, preflight=True):
        """`preflight=False` skips the iw-phy AP-mode check."""
        driver = _phy_driver(self.phyname)
        for message in wifi_profile_messages(
                driver, self.skip_encryption, self.accept_decrypted_ccmp):
            self.info(message)
        if preflight:
            preflight_host(self.phyname, self.log)
        last_err = None
        for attempt in range(1, attempts + 1):
            free_radio({self.phyname}, self.log)
            self._err = None
            self._ready.clear()
            self._stop.clear()
            self._thread = threading.Thread(target=self._run_host, daemon=True)
            self._thread.start()
            if not self._ready.wait(timeout):
                last_err = f"LDN host bring-up timed out after {timeout}s (attempt {attempt}/{attempts})"
                self.log(f"[host] {last_err}")
                self._stop.set()
            elif self._err:
                last_err = self._err
            else:
                self._assert_vifs()
                tune_iface(self.iface, self.our_ip, self.broadcast, self.log)
                self._setup_sockets()
                if attempt > 1:
                    self.log(f"[host] AP up on attempt {attempt}/{attempts}.")
                return self
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=2)
            if attempt < attempts:
                self.log(f"[host] retrying AP bring-up in {settle}s (attempt {attempt + 1}/{attempts})...")
                time.sleep(settle)
        light_cleanup(self.log)
        raise RuntimeError(f"LDN host bring-up failed after {attempts} attempt(s):\n{last_err}")

    def _run_host(self):
        try:
            import trio
            import ldn
        except ImportError as e:                        # pragma: no cover
            self._err = f"missing dep for host mode: {e}"
            self._ready.set()
            return

        async def main():
            keys = ldn.load_keys(self.keys_path)
            param = ldn.CreateNetworkParam()
            param.protocol = 3
            param.keys = keys
            param.local_communication_id = self.LOCAL_COMMUNICATION_ID
            param.scene_id = self.SCENE_ID
            param.app_version = self.APPLICATION_VERSION
            param.max_participants = self.max_participants
            param.accept_policy = ldn.ACCEPT_ALL
            param.application_data = self.app_data
            param.password = self.password
            param.name = self.nickname.encode()
            param.phyname = self.phyname
            param.phyname_monitor = self.phyname
            param.ifname = self.ap_ifname
            param.ifname_monitor = self.mon_ifname
            param.ifname_tap = self.ifname
            param.skip_encryption = self.skip_encryption
            param.accept_decrypted_ccmp = self.accept_decrypted_ccmp
            if self.channel is not None:
                param.channel = self.channel
            tx_mode = ("mac80211/hardware" if self.skip_encryption
                       else "LDN software")
            rx_mode = ("driver-decrypted retained-CCMP normalization"
                       if self.accept_decrypted_ccmp else "standard CCMP")
            self.info(f"Wi-Fi compatibility active: TX={tx_mode}; RX={rx_mode}.")
            self.info("Creating the LDN network (hosting)...")
            async with ldn.create_network(param) as network:
                self._network = network
                if self.tracer is not None:
                    from . import ldntrace
                    ldntrace.attach(network, self.tracer, self.log)
                info = network.info()
                self.ssid = info.ssid
                me = network.participant()
                self.our_ip = me.ip_address
                self.host_ip = me.ip_address
                self.our_mac = bytes(me.mac_address)
                self.broadcast = network.broadcast_address()
                self.iface = self.ifname
                self.log(f"[host] AP up: ssid={self.ssid.hex()} ch={info.channel} "
                         f"us={self.our_ip}/{self.our_mac.hex()} bcast={self.broadcast} "
                         f"comm_id=0x{self.LOCAL_COMMUNICATION_ID:016x} beacon={len(self.app_data)}B")
                self.info(f"Hosting. Waiting for the console to join "
                          f"(ssid={self.ssid.hex()[:8]}..., channel {info.channel}).")
                self._ready.set()
                while not self._stop.is_set():
                    with trio.move_on_after(0.2):
                        event = await network.next_event()
                        self._on_event(event, network)

        try:
            trio.run(main)
        except BaseException as e:                        # pragma: no cover
            self._err = _format_join_error(e)
            self.log(f"[host] LDN host bring-up FAILED:\n{self._err}")
            self._ready.set()

    def _on_event(self, event, network):
        name = type(event).__name__
        if name == "JoinEvent":
            p = event.participant
            self.join_events += 1
            self.participants.append((event.index, p.ip_address, bytes(p.mac_address), bytes(p.name)))
            self.log(f"[host] *** CONSOLE JOINED *** idx={event.index} ip={p.ip_address} "
                     f"mac={bytes(p.mac_address).hex()} name={bytes(p.name)!r}")
            self.info("A console joined the network.")
        elif name == "LeaveEvent":
            # The host drivers use this list as their liveness/teardown signal; stale entries kept RTT/Reliable going to a departed station.
            self.participants = [p for p in self.participants if p[0] != event.index]
            reason = getattr(event, "reason", None)
            management_type = getattr(event, "management_type", None)
            detail = ""
            if reason is not None:
                detail = f" via {management_type or 'management frame'} reason={reason}"
            self.log(f"[host] console left: idx={event.index}{detail}")
        else:
            self.log(f"[host] event: {name} {event!r}")

    def _assert_vifs(self):
        """Three vifs must exist: AP (mgmt/auth), monitor (advertisements + data frames incl. broadcast), tap (the kernel data
        plane); a missing monitor means the console never sees an advertisement.
        """
        missing = []
        for name, want in ((self.ap_ifname, "AP"), (self.mon_ifname, "monitor"), (self.ifname, "tap")):
            if not _iface_exists(name):
                missing.append(f"{name} ({want})")
                continue
            typ = "tap"
            try:
                out = subprocess.check_output(["iw", "dev", name, "info"],
                                              text=True, stderr=subprocess.DEVNULL)
                for line in out.splitlines():
                    if line.strip().startswith("type "):
                        typ = line.strip().split()[1]
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
            self.log(f"[host] vif check: {name} present (type {typ}, want {want})")
        if missing:
            self.log(f"[host] vif check WARNING - missing: {', '.join(missing)}; "
                     f"hosting will not work correctly")

    def set_application_data(self, data):
        self.app_data = bytes(data)
        if self._network is not None:
            try:
                self._network.set_application_data(self.app_data)
            except Exception as e:                        # pragma: no cover
                self.log(f"[host] set_application_data failed: {e}")

    def _setup_sockets(self):
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Unbound, limited broadcasts occasionally left on another link-local interface; Session type 5 is a subnet
        # broadcast, so pin every host datagram to the LDN data plane.
        tx.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                      self.iface.encode("ascii") + b"\x00")
        tx.bind(("0.0.0.0", PIA_PORT))
        self._tx = tx
        rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_IP))
        rx.bind((self.iface, 0))
        rx.setblocking(False)
        try:
            rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
        except OSError as e:                              # pragma: no cover
            self.log(f"[host] could not enlarge rx SO_RCVBUF: {e}")
        self._rx = rx
        self._pinned_neighbours = set()

    def send(self, datagram, dst_ip):
        dst = self.broadcast if dst_ip in (self.broadcast, "255.255.255.255") else dst_ip
        if self.tracer is not None:
            self.tracer.write("udp_out", dst=dst, hex=bytes(datagram).hex())
        try:
            self._tx.sendto(datagram, (dst, PIA_PORT))
        except BlockingIOError:
            # The console stops acking ~0.5s during its flash save; a blocking sendto froze the host 6-11s, so drop what
            # cannot be queued (Reliable re-sends it).
            self.tx_dropped = getattr(self, "tx_dropped", 0) + 1
            if self.tx_dropped in (1, 10, 100, 1000):
                self.log(f"[host] sendto would block; dropped {self.tx_dropped} datagram(s) so far")
        except OSError as e:                              # pragma: no cover
            self.log(f"[host] sendto failed: {e}")

    def recv(self):
        out = []
        if self._rx is None:
            return out
        while True:
            try:
                data = self._rx.recv(65535)
            except (BlockingIOError, OSError):
                break
            parsed = LiveTransport._parse_udp(data)
            if parsed is None:
                continue
            src_ip, src_port, dst_ip, dst_port, payload = parsed
            if src_ip == self.our_ip or dst_port != PIA_PORT:
                continue
            self._rx_seen += 1
            if self._rx_seen <= 10:
                self.log(f"[host] RX #{self._rx_seen}: {src_ip} -> {dst_ip}:{dst_port} "
                         f"len={len(payload)} {payload[:4].hex()}")
            if src_ip not in self._pinned_neighbours:
                self._pin_neighbour(src_ip, data[6:12])
            if self.tracer is not None:
                self.tracer.write("udp_in", src=src_ip, dst=dst_ip, hex=payload.hex())
            out.append((payload, src_ip))
        return out

    def _pin_neighbour(self, ip, mac):
        """Install a PERMANENT ARP entry for the console (session 20, u21/u22/u25/u26). The console answers our ARP
        probes late (1-2 s) and by broadcast, so the kernel's neighbour entry cycles STALE -> PROBE -> FAILED ->
        INCOMPLETE and, while unresolved, queues every datagram to it (unres_qlen) and flushes them in a burst when
        the reply lands: a 0.1-1.1 s hole in which the console sees no parent frame, and its game declares link loss.
        A permanent entry never expires, so the kernel never probes and never queues.
        """
        self._pinned_neighbours.add(ip)
        mac_s = ":".join(f"{b:02x}" for b in mac)
        cmd = ["ip", "neigh", "replace", ip, "lladdr", mac_s, "dev", self.iface, "nud", "permanent"]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            self.log(f"[host] pinned ARP {ip} -> {mac_s} on {self.iface} (permanent); no neighbour probing for the console")
        except Exception as e:                            # pragma: no cover
            self.log(f"[host] could not pin ARP for {ip}: {e}")

    def wait_readable(self, timeout):
        """select() on the AF_PACKET socket so the leader reacts as soon as a packet lands while still returning periodically
        for event/deadline checks.
        """
        timeout = max(0.0, float(timeout))
        if self._rx is None:
            self._stop.wait(timeout)
            return False
        try:
            readable, _, _ = select.select([self._rx], [], [], timeout)
        except (OSError, ValueError):
            return False
        return bool(readable)

    def stop(self):
        self._stop.set()
        for s in (self._tx, self._rx):
            try:
                if s:
                    s.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        light_cleanup(self.log)
