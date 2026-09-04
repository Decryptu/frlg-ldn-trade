---
title: Hardware and setup
nav_order: 5
has_children: true
---

# Hardware and setup

Speaking LDN needs an adapter the kernel will put into AP mode and keep there, and the failures
look like anything but what they are. The USB mode switch reads as a hypervisor problem; a missing
`accept_decrypted_ccmp` reads as a silent host; `failed to get tx report from firmware` in `dmesg`
is our own teardown and not a wedged adapter.

Read the adapter page before blaming the adapter.
