# VeSync (Turbo Tower Pro fork)

Home Assistant 2026.9.3 `vesync` integration, overriding the built-in one to use
[gnisch/pyvesync](https://github.com/gnisch/pyvesync/tree/feat/turbo-tower-pro-dc123)
with support for the Cosori Turbo Tower Pro Smart dual-chamber air fryer
(CAF-DC111S / CAF-DC123S).

Changes from core:
- `pyvesync` installed from the fork.
- Air fryer cooking status accepts `ready` (program prepared, waiting for Start).
- Per-chamber status, set temperature and remaining time sensors.

Remove this integration from HACS and restart to go back to the built-in one.
