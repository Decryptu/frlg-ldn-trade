# Vendored LDN

This directory contains the minimal distributable source for the `ldn` Python
package used by `frlg-ldn-trade`. It is deliberately tracked in this repository
so a fresh clone has the exact WLAN implementation tested with the project.

## Upstream

- Project: <https://github.com/kinnay/LDN>
- Upstream revision: `39d0b2060c7932ff2766726db7af4fb640cfa9ef`
- Upstream package version: `0.0.17`
- License: GPL-3.0-only; the complete upstream license is in `LICENSE`.

The vendored contents are limited to the package source, packaging metadata,
and license. Upstream Git metadata, examples, documentation, wiki, caches, and
other non-runtime material are intentionally excluded.

## Local compatibility changes

The vendored package incorporates the following project-specific fixes:

- Strip a trailing FCS when Radiotap reports it and accept explicitly opted-in
  Realtek monitor frames that are already CCMP-decrypted but retain CCMP
  metadata (`accept_decrypted_ccmp`).
- Preserve the Ethernet destination when sending frames delegated to
  mac80211/hardware CCMP (`skip_encryption`).
- Mark a station authorized in mac80211 once custom LDN authentication has
  completed.
- Emit useful receive-side exceptions instead of silently suppressing them.

Keep this file current whenever the vendored copy is rebased or modified.
