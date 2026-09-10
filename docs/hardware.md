---
title: Hardware and setup
nav_order: 7
has_children: true
---

# Hardware and setup

Speaking LDN needs an adapter the kernel will put into AP mode and keep there.

| symptom | cause |
|---|---|
| a hypervisor-style USB disconnect at AP start | the USB mode switch; see [Adapters](hardware_adapters.md) |
| a silent host | `accept_decrypted_ccmp` unset |
| `failed to get tx report from firmware` in `dmesg` | the host's own teardown |

## Pages

- [Adapters](hardware_adapters.md): tested cards, the reference USB adapter, and its configuration.
- [Raspberry Pi host](hardware_raspberry_pi.md): deployment and the supervised Mystery Gift runner.
- [Switch keys](hardware_switch_keys.md): installing `prod.keys` safely.
