---
title: Adapters
parent: Hardware and setup
nav_order: 1
---

# Wi-Fi adapters

## Tested cards

| model | type | driver | reliability |
|---|---|---|---|
| TP-Link Archer T3U (`2357:012d`) | external USB | `rtw88_8822bu` | high; the reference host adapter |
| ALFA AWUS036ACHM | external USB | `mt76x0u` | high |
| Realtek RTL8821CE | internal PCIe | `rtw88_8821ce` | high |
| AMD RZ616 | internal M.2 | `mt7921e` | low; about half the speed and sometimes deadlocks before exiting |
| MT7601U | external USB | `mt7601u` | needs the project-pinned `mt7601u-ap` DKMS module; the stock driver has monitor mode but does not advertise AP mode |

Known not to work:

| model | type | driver | issue |
|---|---|---|---|
| Intel AX200 | internal M.2 | `iwlwifi` | cannot be assigned an IP |
| Atheros AR9271 | external USB | `ath9k_htc` | cannot be assigned an IP most of the time |

## Host modes

`--skip-encryption` skips LDN's Python CCMP step and lets mac80211 or the hardware apply CCMP once;
traffic stays encrypted over the air. Both proven adapters need it.

`--accept-decrypted-ccmp` is a receive path for monitor drivers that retain CCMP metadata around
hardware-decrypted plaintext. The Archer T3U's `rtw88_8822bu` monitor interface reports a Protected
frame with its CCMP header and MIC retained around already-decrypted receive data; the option removes
the retained MIC before forwarding the plaintext to `ldn-tap`. Keep it disabled for the ALFA, which
exposes standard receive frames.

| adapter | normal host configuration |
|---|---|
| TP-Link Archer T3U | the checked-in `config/host.toml` profile; no Wi-Fi flags required |
| ALFA AWUS036ACHM | `--phy phyN --skip-encryption --no-accept-decrypted-ccmp` |

With `phy = "auto"`, the named adapter profile resolves only the matching `rtw88_8822bu` USB
`2357:012d` device and fails if the adapter is missing or more than one matches. An explicit
`--phy phyN` always wins. Startup prints the detected profile, the active transmit and receive modes,
and a warning if the flags do not match the proven profile.

Do not hardcode a phy number. It changes on every re-enumeration. Reserve `--phy phyN` for one-off
debugging.

# The TP-Link Archer T3U

`rtw88_8822bu` is in the mainline kernel since 6.11 and lists this USB id; no out-of-tree driver is
needed. Confirm the kernel can bind it:

```bash
modinfo rtw88_8822bu | grep -i 2357
lsusb | grep -i 2357
iw dev
```

## Keep NetworkManager off the adapter itself

The adapter's own interface appears on hotplug with a name such as `wlx58d8122149a2`; NetworkManager
claims it, starts a background scan, and the channel change takes the radio down mid-run, about
eleven seconds after the interface appears:

```text
rtw88_8822bu 3-1:1.0: write register 0x81c failed with -71
usb 3-1: USB disconnect, device number 2
```

Exclude the adapter interface as well as the LDN interfaces:

```text
# /etc/NetworkManager/conf.d/zz-ldn-unmanaged.conf
[keyfile]
unmanaged-devices=interface-name:ldnclient;interface-name:ldn;interface-name:ldn-mon;interface-name:ldn-tap;interface-name:wlx*;interface-name:wlan*
```

Reload NetworkManager and verify that `nmcli device status` reports the adapter as `unmanaged`. The
file must sort last (`zz-` prefix): some distributions ship a later-sorting file that sets
`unmanaged-devices=none`.

Without the `ldnclient` exclusion, a join creates a fresh `ldnclient` interface mid-run,
NetworkManager grabs it and points wpa_supplicant at it, and the join fails with `[Errno 114] Match
already configured`. Verify with `NetworkManager --print-config | grep unmanaged`.

## Disable the driver's USB 3 mode switch

`rtw88_usb` defaults to `switch_usb_mode=Y`, which moves the adapter into USB 3 mode after the driver
loads by a USB re-enumeration. A hypervisor passing the device through reports the re-enumeration as
a disconnect, and the LDN interfaces disappear with it. The host then dies about one second after it
starts hosting:

```text
RuntimeError: 802.11 beacon injector stopped: [Errno 100] Network is down
```

There is no preceding driver error. The parameter's own description notes that USB 3 mode can
interfere with the 2.4 GHz band, the band LDN uses.

```text
# /etc/modprobe.d/rtw88-ldn.conf
options rtw88_usb switch_usb_mode=N
options rtw88_core disable_lps_deep=Y
```

Unplug and replug the adapter afterwards: the device stays in USB 3 mode until it loses power. A
correct result reports high speed:

```bash
cat /sys/bus/usb/devices/*/speed     # 480, not 5000
cat /sys/bus/usb/devices/*/version   # 2.10, not 3.00
```

With the mode switch enabled the adapter enumerates twice per plug-in, once at high speed and once
at SuperSpeed. With `switch_usb_mode=N` it attaches once.

## Bring the adapter interface down before a run

A managed interface that is up holds the radio's channel. `transport.free_radio()` lowers it; a bare
`tools/ldn/ldn_scan.py` does not:

```text
OSError: [Errno 16] Device or resource busy
```

```bash
sudo ip link set wlxXXXXXXXXXXXX down
```

A kill script that ends by bringing the base interface back up makes the next launch fail with that
error. A "clean" check means the base interface is down. Anything that raises it for a kernel
`iw scan` must lower it again before handing over.

## Verify

```bash
./scripts/preflight_pi.sh
```

The script runs on any Linux host.
