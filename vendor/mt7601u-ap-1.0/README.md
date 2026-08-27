# mt7601u-ap 1.0

This is the Linux `mt7601u` driver source packaged for DKMS.  It is the
desktop-tested custom module used by this project for MT7601U USB adapters.

The one intentional functional difference from the matching upstream driver
source is in `init.c`: it advertises `NL80211_IFTYPE_AP` in addition to
station mode.  That makes the adapter usable by the LDN host, which requires
both AP and monitor interfaces.

`dkms.conf` builds the module against the headers for the running kernel and
installs it at `/lib/modules/<kernel>/updates/dkms/mt7601u.ko*`.  Do not copy a
built module between machines; the Pi must build its own ARM64 module.

The source is GPL-2.0-only, as marked in the original driver files.
