---
title: TP-Link Archer T3U
nav_order: 5
---

# TP-Link Archer T3U host adapter

The TP-Link Archer T3U / AC1300 (`2357:012d`, `rtw88_8822bu`) is the reference
USB adapter for hosting. `rtw88_8822bu` has been in the mainline kernel since
6.11 and already lists this USB id, so no DKMS module and no out-of-tree driver
are required. Confirm the kernel can bind it before anything else:

```bash
modinfo rtw88_8822bu | grep -i 2357
lsusb | grep -i 2357
iw dev
```

## Keep NetworkManager off the adapter itself

The exclusion in the README covers the interfaces the LDN library creates during
a run. It does not cover the adapter's own interface, which appears on hotplug
with a predictable name such as `wlx58d8122149a2`. NetworkManager claims that
interface, starts a background scan, and the resulting channel change can take
the radio down mid-run. On a USB adapter the failure looks like this, about
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

Reload NetworkManager and verify that `nmcli device status` reports the adapter
as `unmanaged`. Use a `zz-` prefix so the file sorts last: some distributions
ship a later-sorting file that sets `unmanaged-devices=none`.

## Disable the driver's USB 3 mode switch

`rtw88_usb` defaults to `switch_usb_mode=Y`, which moves the adapter into USB 3
mode after the driver loads. That switch is a USB re-enumeration. A bare metal
kernel absorbs it, but a hypervisor passing the device through reports it as a
disconnect, and the LDN interfaces disappear with it. Under virtualization the
host then dies about one second after it starts hosting:

```text
RuntimeError: 802.11 beacon injector stopped: [Errno 100] Network is down
```

There is no preceding driver error, which is what distinguishes this from a
driver fault. The parameter's own description also notes that USB 3 mode can
interfere with the 2.4 GHz band, which is the band LDN uses.

```text
# /etc/modprobe.d/rtw88-ldn.conf
options rtw88_usb switch_usb_mode=N
options rtw88_core disable_lps_deep=Y
```

Unplug and replug the adapter afterwards. A soft reset is not enough: the device
stays in USB 3 mode until it loses power. A correct result reports high speed:

```bash
cat /sys/bus/usb/devices/*/speed     # 480, not 5000
cat /sys/bus/usb/devices/*/version   # 2.10, not 3.00
```

The adapter also enumerates twice per plug-in while the mode switch is enabled,
once at high speed and once at SuperSpeed. Both events are the same device. With
`switch_usb_mode=N` it attaches once.

## Bring the adapter interface down before a run

`transport.free_radio()` does this automatically, but a manually raised interface
still breaks a bare `ldn_scan.py`, because a managed interface that is up holds
the radio's channel:

```text
OSError: [Errno 16] Device or resource busy
```

```bash
sudo ip link set wlxXXXXXXXXXXXX down
```

## Do not hardcode a phy number

The phy number changes on every re-enumeration, and this adapter re-enumerates
often. The `adapter = "tplink-archer-t3u"` profile resolves the device by driver
and USB id and is the correct mechanism. Reserve `--phy phyN` for one-off
debugging.

## Verify

```bash
./scripts/preflight_pi.sh
```

The script runs on any Linux host, not only a Raspberry Pi.
