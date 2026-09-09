---
title: Hardware and setup
nav_order: 7
has_children: true
---

# Hardware and setup

Speaking LDN needs an adapter the kernel will put into AP mode and keep there. The failures look like
anything but what they are: the USB mode switch reads as a hypervisor problem, a missing
`accept_decrypted_ccmp` reads as a silent host, and `failed to get tx report from firmware` in `dmesg`
is the host's own teardown rather than a wedged adapter.

Read [Adapters](hardware_adapters.md) before blaming the adapter.

## Pages

- [Adapters](hardware_adapters.md) — tested cards, the reference USB adapter, and its configuration.
- [Raspberry Pi host](hardware_raspberry_pi.md) — deployment and the supervised Mystery Gift runner.
- [Switch keys](hardware_switch_keys.md) — installing `prod.keys` safely.
